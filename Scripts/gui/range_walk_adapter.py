"""Qt-independent EdgeTX CSV marker preview for Range-Walk Comparison."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median

from core.edgetx import EdgeTxSession, read_edgetx_csv
from core.range_walk import LandmarkMarker, MarkerCalibration, detect_markers


@dataclass(frozen=True)
class RangeWalkPreviewRequest:
    """One calibrated preview request tied to a GUI source generation."""

    source_path: Path
    down: str
    neutral: str
    near_down: str
    request_id: int


@dataclass(frozen=True)
class RangeWalkInspectionRequest:
    """Read one newly selected CSV without assigning its calibration."""

    source_path: Path
    request_id: int


@dataclass(frozen=True)
class RangeWalkCsvInspection:
    """Observed CSV facts that can help an operator enter calibration."""

    source_path: Path
    request_id: int
    recording_start: datetime
    recording_end: datetime
    row_count: int
    ele_min: float
    ele_max: float
    calibration: "EleCalibrationSuggestions"


@dataclass(frozen=True)
class EleCalibrationSuggestions:
    """Sustained CSV plateaus that may support operator-confirmed calibration."""

    neutral: float | None
    high: float | None
    low: float | None
    explanation: str


@dataclass(frozen=True)
class RangeWalkPreviewResult:
    """Portable marker candidates and their read-only presentation."""

    source_path: Path
    request_id: int
    recording_start: datetime
    recording_end: datetime
    row_count: int
    markers: tuple[LandmarkMarker, ...]
    text: str


def analyse_range_walk_preview(
    request: RangeWalkPreviewRequest,
) -> RangeWalkPreviewResult:
    """Parse one CSV and run the existing calibrated marker detector."""
    source = Path(request.source_path).expanduser().resolve()
    calibration = marker_calibration(
        request.down, request.neutral, request.near_down
    )
    session = read_edgetx_csv(source)
    markers = detect_markers(session, calibration)
    start = session.rows[0].clock
    end = session.rows[-1].clock
    return RangeWalkPreviewResult(
        source,
        request.request_id,
        start,
        end,
        len(session.rows),
        markers,
        _format_preview(source, start, end, len(session.rows), markers),
    )


def inspect_range_walk_csv(
    request: RangeWalkInspectionRequest,
) -> RangeWalkCsvInspection:
    """Read observed Ele bounds without interpreting endpoint direction."""
    source = Path(request.source_path).expanduser().resolve()
    session = read_edgetx_csv(source)
    if session.header.count("Ele") != 1 or any(
        row.ele is None for row in session.rows
    ):
        raise ValueError("Range walk requires one numeric Ele value on every CSV row")
    values = [row.ele for row in session.rows]
    return RangeWalkCsvInspection(
        source,
        request.request_id,
        session.rows[0].clock,
        session.rows[-1].clock,
        len(session.rows),
        min(values),
        max(values),
        estimate_ele_calibration(session),
    )


def estimate_ele_calibration(session: EdgeTxSession) -> EleCalibrationSuggestions:
    """Suggest neutral and sustained endpoints without assigning down direction."""
    if session.header.count("Ele") != 1 or any(
        row.ele is None for row in session.rows
    ):
        return EleCalibrationSuggestions(
            None, None, None, "A numeric Ele value is required on every CSV row."
        )
    rows = session.rows
    values = [row.ele for row in rows]
    if len(rows) < 3 or min(values) == max(values):
        return EleCalibrationSuggestions(
            None, None, None, "The recording has no usable sustained Ele range."
        )
    gaps = [
        (later.clock - earlier.clock).total_seconds()
        for earlier, later in zip(rows, rows[1:])
    ]
    cadence = median(gaps) if gaps else 0.1
    ordered = sorted(values)
    lower = ordered[int(0.05 * (len(ordered) - 1))]
    upper = ordered[int(0.95 * (len(ordered) - 1))]
    tolerance = max(1.0, abs(upper - lower) * 0.015)

    current = [values[0]]
    current_sum = values[0]
    start = rows[0].clock
    sustained: list[tuple[float, int]] = []
    for previous, row in zip(rows, rows[1:]):
        value = row.ele
        gap = (row.clock - previous.clock).total_seconds()
        center = current_sum / len(current)
        if gap <= 2.5 * cadence and abs(value - center) <= tolerance:
            current.append(value)
            current_sum += value
            continue
        if (previous.clock - start).total_seconds() >= 1.0:
            sustained.append((median(current), len(current)))
        current = [value]
        current_sum = value
        start = row.clock
    if (rows[-1].clock - start).total_seconds() >= 1.0:
        sustained.append((median(current), len(current)))
    if not sustained:
        return EleCalibrationSuggestions(
            None, None, None, "No Ele value was sustained long enough to calibrate."
        )

    groups: list[list[tuple[float, int]]] = []
    for plateau in sorted(sustained):
        if groups and abs(plateau[0] - _weighted_center(groups[-1])) <= 2 * tolerance:
            groups[-1].append(plateau)
        else:
            groups.append([plateau])
    ranked = sorted(groups, key=_group_count, reverse=True)
    neutral_group = ranked[0]
    neutral_count = _group_count(neutral_group)
    runner_up = _group_count(ranked[1]) if len(ranked) > 1 else 0
    if neutral_count < max(5, 0.20 * len(rows)) or (
        runner_up and neutral_count < 1.5 * runner_up
    ):
        return EleCalibrationSuggestions(
            None,
            None,
            None,
            "No clearly dominant sustained Ele value identifies neutral; use manual calibration.",
        )

    neutral = _weighted_center(neutral_group)
    centers = [
        _weighted_center(group) for group in groups if group is not neutral_group
    ]
    minimum_separation = max(4 * tolerance, 0.10 * abs(upper - lower))
    high_values = [value for value in centers if value - neutral >= minimum_separation]
    low_values = [value for value in centers if neutral - value >= minimum_separation]
    high = max(high_values, default=None)
    low = min(low_values, default=None)
    if high is None and low is None:
        return EleCalibrationSuggestions(
            neutral,
            None,
            None,
            "Neutral is suggested, but no separated endpoint was sustained; use manual calibration.",
        )
    available = []
    if high is not None:
        available.append("higher endpoint")
    if low is not None:
        available.append("lower endpoint")
    return EleCalibrationSuggestions(
        neutral,
        high,
        low,
        "Suggested from sustained Ele plateaus: " + " and ".join(available) + ".",
    )


def _group_count(group: list[tuple[float, int]]) -> int:
    return sum(count for _value, count in group)


def _weighted_center(group: list[tuple[float, int]]) -> float:
    count = _group_count(group)
    return sum(value * samples for value, samples in group) / count


def marker_calibration(
    down_text: str,
    neutral_text: str,
    near_down_text: str,
) -> MarkerCalibration:
    """Parse explicit operator input and apply existing core validation."""
    down = _required_number(down_text, "Full elevator-down Ele")
    neutral = _required_number(neutral_text, "Neutral Ele")
    near_down = (
        _required_number(near_down_text, "Near-down threshold")
        if near_down_text.strip()
        else None
    )
    return MarkerCalibration(down, neutral, near_down=near_down)


def _required_number(raw: str, label: str) -> float:
    value = raw.strip()
    if not value:
        raise ValueError(f"{label} is required")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be numeric") from exc


def _format_preview(
    source: Path,
    start: datetime,
    end: datetime,
    row_count: int,
    markers: tuple[LandmarkMarker, ...],
) -> str:
    lines = [
        "Range-Walk CSV / marker preview",
        "================================",
        "CSV/marker preview only — comparison not yet connected.",
        f"Source CSV: {source.name}",
        f"Path: {source}",
        "Radio-local recording: "
        f"{start.isoformat(sep=' ', timespec='milliseconds')} to "
        f"{end.isoformat(sep=' ', timespec='milliseconds')}",
        f"CSV rows: {row_count}",
        f"Marker candidates: {len(markers)}",
        "",
        "Detected candidates (not confirmed physical landmarks)",
    ]
    if not markers:
        lines.append("  No complete calibrated elevator-down holds detected.")
    for number, marker in enumerate(markers, start=1):
        lines.append(
            f"  {number}. onset {marker.onset.time().isoformat(timespec='milliseconds')}; "
            f"release {marker.release.time().isoformat(timespec='milliseconds')}; "
            f"hold {marker.hold_s:.3f} s"
        )
    lines.extend(
        [
            "",
            "No baseline, landmark mapping, RF comparison, distance, failsafe "
            "or antenna ranking is established by this preview.",
        ]
    )
    return "\n".join(lines)
