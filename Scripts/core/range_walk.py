"""CSV-only, landmark-bounded ELRS range-walk evidence.

All RF eligibility comes from the existing EdgeTX row classification. No aircraft
failsafe state, physical range, or RF sensor refresh time is inferred here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from statistics import median

from .edgetx import EdgeTxRow, EdgeTxSession


RF_FIELDS = ("1RSS(dB)", "RQly(%)", "RSNR(dB)")
AVAILABILITIES = ("active", "partial", "unavailable", "ambiguous")


@dataclass(frozen=True)
class LandmarkMarker:
    onset: datetime
    release: datetime
    down_sample_count: int

    @property
    def hold_s(self) -> float:
        return (self.release - self.onset).total_seconds()


@dataclass(frozen=True)
class MarkerCalibration:
    """Operator-confirmed radio-local endpoint and neutral for this model/run."""

    down: float
    neutral: float
    min_hold_s: float = 1.5
    near_down: float | None = None
    neutral_tolerance: float = 0.20

    def __post_init__(self):
        if (not all(math.isfinite(value) for value in
                    (self.down, self.neutral, self.min_hold_s,
                     self.neutral_tolerance)) or
                self.down == self.neutral or self.min_hold_s <= 0 or
                not 0 < self.neutral_tolerance <= 1):
            raise ValueError("Calibrated down must differ from neutral; hold must be positive")
        if self.near_down is not None:
            if (not math.isfinite(self.near_down) or
                    not 0 < (self.near_down - self.neutral) /
                    (self.down - self.neutral) <= 1):
                raise ValueError("Near-down threshold must lie between neutral and down")

    def is_down(self, value: float) -> bool:
        delta = self.down - self.neutral
        threshold = (self.near_down if self.near_down is not None else
                     self.neutral + 0.875 * delta)
        return (value - threshold) * (1 if delta > 0 else -1) >= 0

    def is_neutral(self, value: float) -> bool:
        return abs(value - self.neutral) <= self.neutral_tolerance * abs(
            self.down - self.neutral
        )


def _cadence_s(rows: list[EdgeTxRow]) -> float:
    gaps = [(b.clock - a.clock).total_seconds() for a, b in zip(rows, rows[1:])]
    return median(gaps) if gaps else 0.1


def detect_markers(session: EdgeTxSession,
                   calibration: MarkerCalibration) -> tuple[LandmarkMarker, ...]:
    """Find complete down-hold/neutral-return candidates, independent of RF gaps."""
    if session.header.count("Ele") != 1 or any(row.ele is None for row in session.rows):
        raise ValueError("Range walk requires one numeric Ele value on every CSV row")
    rows = session.rows
    cadence = _cadence_s(rows)
    max_internal_gap = 2.5 * cadence
    down_indices = [i for i, row in enumerate(rows)
                    if calibration.is_down(row.ele)]
    clusters: list[list[int]] = []
    for index in down_indices:
        if not clusters or (rows[index].clock - rows[clusters[-1][-1]].clock
                            ).total_seconds() > max_internal_gap:
            clusters.append([index])
        else:
            clusters[-1].append(index)

    candidates = []
    for cluster in clusters:
        first, last = cluster[0], cluster[-1]
        if (rows[last].clock - rows[first].clock).total_seconds() < calibration.min_hold_s:
            continue
        before = next((i for i in range(first - 1, -1, -1)
                       if calibration.is_neutral(rows[i].ele)), None)
        after = next((i for i in range(last + 1, len(rows))
                      if calibration.is_neutral(rows[i].ele)), None)
        if before is None or after is None:
            continue
        if ((rows[first].clock - rows[before].clock).total_seconds() > 1.0 or
                (rows[after].clock - rows[last].clock).total_seconds() > 1.0):
            continue
        marker = LandmarkMarker(rows[first].clock, rows[after].clock, len(cluster))
        if candidates and (marker.onset - candidates[-1].release).total_seconds() < 0.5:
            previous = candidates[-1]
            candidates[-1] = LandmarkMarker(previous.onset, marker.release,
                                             previous.down_sample_count + len(cluster))
        else:
            candidates.append(marker)
    return tuple(candidates)


def select_landmarks(candidates: tuple[LandmarkMarker, ...],
                     numbers: tuple[int | None, ...], *, baseline: bool = False
                     ) -> tuple[LandmarkMarker | None, ...]:
    """Use five explicit 1-based candidate numbers; None denotes a missing mark."""
    if len(numbers) != 5 or (baseline and any(number is None for number in numbers)):
        raise ValueError("Walk 1 needs five confirmed landmarks; every walk needs five mappings")
    used = [number for number in numbers if number is not None]
    if used != sorted(set(used)) or any(n < 1 or n > len(candidates) for n in used):
        raise ValueError("Landmark selections must be distinct, increasing candidates")
    return tuple(candidates[n - 1] if n is not None else None for n in numbers)


@dataclass(frozen=True)
class WalkSettings:
    tx_power: str = ""
    packet_rate: str = ""
    rf_mode: str = ""
    dynamic_power: str = ""


@dataclass(frozen=True)
class IntervalEvidence:
    start: datetime
    end: datetime
    row_count: int
    availability_counts: dict[str, int]
    availability_time_s: dict[str, float]
    unlogged_time_s: float
    usable_counts: dict[str, int]
    usable_time_s: dict[str, float]
    median_values: dict[str, float | None]
    p10_values: dict[str, float | None]
    tqly_median: float | None
    longest_unavailable_s: float

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def rssi_coverage(self) -> float:
        return self.usable_time_s["1RSS(dB)"] / self.duration_s if self.duration_s else 0


def _p10(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = 0.1 * (len(ordered) - 1)
    lower = int(position)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[min(lower + 1, len(ordered) - 1)]
                                      - ordered[lower])


def interval_evidence(session: EdgeTxSession, start: datetime,
                      end: datetime) -> IntervalEvidence:
    """Summarise eligible logged values and bounded row-time coverage."""
    if end <= start:
        raise ValueError("Evidence interval must have positive duration")
    rows = session.rows
    cadence = _cadence_s(rows)
    selected = [(i, row) for i, row in enumerate(rows) if start <= row.clock < end]
    counts = {name: 0 for name in AVAILABILITIES}
    times = {name: 0.0 for name in AVAILABILITIES}
    values = {name: [] for name in RF_FIELDS}
    usable_time = {name: 0.0 for name in RF_FIELDS}
    tqly = []
    longest_gap = current_gap = 0.0
    previous_end: datetime | None = None
    for index, row in selected:
        following = rows[index + 1].clock if index + 1 < len(rows) else end
        cell_end = min(end, following, row.clock + timedelta(seconds=1.5 * cadence))
        cell_s = max(0.0, (cell_end - row.clock).total_seconds())
        counts[row.availability] += 1
        times[row.availability] += cell_s
        if row.availability == "unavailable":
            if previous_end is not None and row.clock <= previous_end:
                current_gap += cell_s
            else:
                current_gap = cell_s
            longest_gap = max(longest_gap, current_gap)
        else:
            current_gap = 0.0
        previous_end = cell_end
        for field in RF_FIELDS:
            observed = row.observed(field)
            if observed is not None:
                values[field].append(observed)
                usable_time[field] += cell_s
        reported_tqly = row.values.get("TQly(%)")
        if (row.availability == "active" and reported_tqly is not None
                and 0 <= reported_tqly <= 100):
            tqly.append(reported_tqly)
    duration = (end - start).total_seconds()
    return IntervalEvidence(
        start, end, len(selected), counts, times,
        max(0.0, duration - sum(times.values())),
        {name: len(values[name]) for name in RF_FIELDS}, usable_time,
        {name: median(values[name]) if values[name] else None for name in RF_FIELDS},
        {name: _p10(values[name]) for name in RF_FIELDS},
        median(tqly) if tqly else None, longest_gap,
    )


@dataclass(frozen=True)
class WalkEvidence:
    session: EdgeTxSession
    label: str
    antenna: str
    settings: WalkSettings
    candidates: tuple[LandmarkMarker, ...]
    landmarks: tuple[LandmarkMarker | None, ...]
    sections: tuple[IntervalEvidence | None, ...]
    holds: tuple[IntervalEvidence | None, ...]


def build_walk(session: EdgeTxSession, label: str, antenna: str,
               settings: WalkSettings, calibration: MarkerCalibration,
               selected: tuple[int | None, ...], *, baseline: bool = False) -> WalkEvidence:
    candidates = detect_markers(session, calibration)
    landmarks = select_landmarks(candidates, selected, baseline=baseline)
    return build_walk_from_landmarks(
        session, label, antenna, settings, candidates, landmarks
    )


def build_walk_from_landmarks(
    session: EdgeTxSession,
    label: str,
    antenna: str,
    settings: WalkSettings,
    candidates: tuple[LandmarkMarker, ...],
    landmarks: tuple[LandmarkMarker | None, ...],
) -> WalkEvidence:
    """Build RF evidence from an already-confirmed five-landmark mapping."""
    if len(landmarks) != 5:
        raise ValueError("Range walk requires five landmark positions")
    sections = tuple(
        interval_evidence(session, first.release, second.onset)
        if first and second and first.release < second.onset else None
        for first, second in zip(landmarks, landmarks[1:])
    )
    holds = tuple(interval_evidence(session, marker.onset, marker.release)
                  if marker else None for marker in landmarks)
    return WalkEvidence(session, label, antenna, settings, candidates,
                        landmarks, sections, holds)


def settings_comparable(baseline: WalkEvidence, other: WalkEvidence) -> bool:
    """Configured settings must be present and identical for qualified comparison."""
    left = baseline.settings
    right = other.settings
    configured = all(a and b and a == b for a, b in zip(
        (left.tx_power, left.packet_rate, left.rf_mode, left.dynamic_power),
        (right.tx_power, right.packet_rate, right.rf_mode, right.dynamic_power),
    ))
    if not configured or left.dynamic_power.casefold() != "off":
        return False
    for field in ("TPWR(mW)", "RFMD"):
        observed = [
            {value for row in walk.session.rows
             if (value := row.observed(field)) is not None}
            for walk in (baseline, other)
        ]
        if any(len(values) > 1 for values in observed):
            return False
        if all(observed) and observed[0] != observed[1]:
            return False
    return True
