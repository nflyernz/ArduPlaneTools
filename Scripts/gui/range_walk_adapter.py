"""Qt-independent EdgeTX CSV marker preview for Range-Walk Comparison."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median

from core.edgetx import EdgeTxSession, read_edgetx_csv
from core.range_walk import (
    LandmarkMarker,
    MarkerCalibration,
    WalkSettings,
    detect_markers,
    select_landmarks,
)


@dataclass(frozen=True)
class RangeWalkPreviewRequest:
    """One automatic-direction preview tied to a GUI source generation."""

    source_path: Path
    inverse: bool
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
    """Sustained CSV plateaus available to automatic direction evaluation."""

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
    direction_used: str
    auto_preferred: str | None
    direction_reliable: bool
    assessment: str
    text: str


@dataclass(frozen=True)
class Walk1Baseline:
    """Validated session-only Walk 1 state using the GUI-detected evidence."""

    source_path: Path
    label: str
    antenna: str
    landmark_names: tuple[str, ...]
    turnaround: str
    settings: WalkSettings
    candidates: tuple[LandmarkMarker, ...]
    candidate_numbers: tuple[int, ...]
    landmarks: tuple[LandmarkMarker, ...]
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime


def create_walk1_baseline(
    preview: RangeWalkPreviewResult,
    candidate_numbers: tuple[int | None, ...],
    landmark_names: tuple[str, ...],
    antenna: str,
    label: str,
    settings: WalkSettings,
) -> Walk1Baseline:
    """Validate and retain a Walk 1 baseline without redetecting markers."""
    if len(landmark_names) != 5 or any(not name.strip() for name in landmark_names):
        raise ValueError("Enter a physical name for all five landmarks")
    if not antenna.strip():
        raise ValueError("Enter the original receiver antenna installation")
    names = tuple(name.strip() for name in landmark_names)
    selected = select_landmarks(
        preview.markers,
        candidate_numbers,
        baseline=True,
    )
    landmarks = tuple(marker for marker in selected if marker is not None)
    numbers = tuple(number for number in candidate_numbers if number is not None)
    return Walk1Baseline(
        source_path=preview.source_path,
        label=label.strip() or f"Walk 1 — {preview.source_path.stem}",
        antenna=antenna.strip(),
        landmark_names=names,
        turnaround=names[4],
        settings=settings,
        candidates=preview.markers,
        candidate_numbers=numbers,
        landmarks=landmarks,
        direction_used=preview.direction_used,
        direction_assessment=preview.assessment,
        recording_start=preview.recording_start,
        recording_end=preview.recording_end,
    )


def format_walk1_baseline_summary(baseline: Walk1Baseline) -> str:
    """Format a compact saved-in-session baseline summary."""
    lines = [
        "Walk 1 baseline",
        "===============",
        f"Label: {baseline.label}",
        f"Source CSV: {baseline.source_path}",
        f"Original receiver antenna: {baseline.antenna}",
        f"Detection direction: {_direction_label(baseline.direction_used)}",
        "",
        "Confirmed landmarks",
    ]
    for position, (name, number, marker) in enumerate(
        zip(
            baseline.landmark_names,
            baseline.candidate_numbers,
            baseline.landmarks,
        ),
        start=1,
    ):
        suffix = " — turnaround" if position == 5 else ""
        lines.append(
            f"  {position}. {name}{suffix}: candidate {number}; "
            f"{marker.onset.time().isoformat(timespec='milliseconds')} to "
            f"{marker.release.time().isoformat(timespec='milliseconds')}; "
            f"hold {marker.hold_s:.3f} s"
        )
    lines.extend(
        [
            f"Safe turnaround: {baseline.turnaround}",
            "",
            "Configured RF settings",
            f"  TX power: {baseline.settings.tx_power or 'Unknown'}",
            f"  Packet rate: {baseline.settings.packet_rate or 'Unknown'}",
            f"  RF mode/band: {baseline.settings.rf_mode or 'Unknown'}",
            f"  Dynamic TX power: {baseline.settings.dynamic_power or 'Unknown'}",
        ]
    )
    if not all(
        (
            baseline.settings.tx_power,
            baseline.settings.packet_rate,
            baseline.settings.rf_mode,
            baseline.settings.dynamic_power,
        )
    ):
        lines.extend(
            [
                "",
                "Warning: unknown RF settings prevent a later like-for-like "
                "comparison claim.",
            ]
        )
    lines.append("Validated baseline retains the exact confirmed marker evidence.")
    return "\n".join(lines)


def analyse_range_walk_preview(
    request: RangeWalkPreviewRequest,
) -> RangeWalkPreviewResult:
    """Parse one CSV and run the existing calibrated marker detector."""
    source = Path(request.source_path).expanduser().resolve()
    session = read_edgetx_csv(source)
    _require_numeric_ele(session)
    suggestions = estimate_ele_calibration(session)
    evaluations = {
        "higher": _direction_markers(session, suggestions.neutral, suggestions.high),
        "lower": _direction_markers(session, suggestions.neutral, suggestions.low),
    }
    auto_direction, reliable = _auto_direction(evaluations, suggestions)
    direction = _opposite(auto_direction) if request.inverse else auto_direction
    markers = evaluations[direction]
    assessment = _direction_assessment(
        request.inverse,
        direction,
        auto_direction,
        reliable,
        evaluations,
        suggestions,
    )
    start = session.rows[0].clock
    end = session.rows[-1].clock
    return RangeWalkPreviewResult(
        source,
        request.request_id,
        start,
        end,
        len(session.rows),
        markers,
        direction,
        auto_direction if reliable else None,
        reliable,
        assessment,
        _format_preview(
            source,
            start,
            end,
            len(session.rows),
            markers,
            direction,
            assessment,
        ),
    )


def _direction_markers(
    session: EdgeTxSession,
    neutral: float | None,
    endpoint: float | None,
) -> tuple[LandmarkMarker, ...]:
    if neutral is None or endpoint is None:
        return ()
    return detect_markers(
        session,
        MarkerCalibration(
            endpoint,
            neutral,
            neutral_tolerance=0.33,
        ),
    )


def _auto_direction(
    evaluations: dict[str, tuple[LandmarkMarker, ...]],
    suggestions: EleCalibrationSuggestions,
) -> tuple[str, bool]:
    high_count = len(evaluations["higher"])
    low_count = len(evaluations["lower"])
    stronger = "higher" if high_count > low_count else "lower"
    strongest = max(high_count, low_count)
    weakest = min(high_count, low_count)
    reliable = strongest >= 2 and strongest - weakest >= 2
    if reliable:
        return stronger, True
    if high_count != low_count:
        return stronger, False
    if suggestions.high is not None:
        return "higher", False
    if suggestions.low is not None:
        return "lower", False
    return "higher", False


def _opposite(direction: str) -> str:
    return "lower" if direction == "higher" else "higher"


def _direction_assessment(
    inverse: bool,
    direction: str,
    auto_direction: str,
    reliable: bool,
    evaluations: dict[str, tuple[LandmarkMarker, ...]],
    suggestions: EleCalibrationSuggestions,
) -> str:
    high_count = len(evaluations["higher"])
    low_count = len(evaluations["lower"])
    selected_count = len(evaluations[direction])
    if selected_count == 0:
        if inverse:
            return "No complete elevator holds were detected in the inverse direction."
        return "No clear elevator stick deflections detected. Try Inverse."
    if inverse:
        qualifier = "clear Auto preference" if reliable else "deterministic Auto fallback"
        return (
            f"Inverse used the opposite of the {qualifier}: {direction}. "
            f"Complete holds: higher {high_count}, lower {low_count}."
        )
    if reliable:
        return (
            f"Auto selected {auto_direction}: its complete sustained-hold sequence "
            f"was clearly stronger (higher {high_count}, lower {low_count})."
        )
    return (
        "Direction evidence is ambiguous or insufficient; Auto used "
        f"{auto_direction} deterministically (higher {high_count}, lower {low_count}). "
        f"{suggestions.explanation} Try Inverse and review the field record."
    )


def inspect_range_walk_csv(
    request: RangeWalkInspectionRequest,
) -> RangeWalkCsvInspection:
    """Read observed Ele bounds without interpreting endpoint direction."""
    source = Path(request.source_path).expanduser().resolve()
    session = read_edgetx_csv(source)
    _require_numeric_ele(session)
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


def _require_numeric_ele(session: EdgeTxSession) -> None:
    if session.header.count("Ele") != 1 or any(
        row.ele is None for row in session.rows
    ):
        raise ValueError("Range walk requires one numeric Ele value on every CSV row")


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
    value_counts = Counter(values)
    neutral, neutral_count = value_counts.most_common(1)[0]
    runner_up = value_counts.most_common(2)[1][1] if len(value_counts) > 1 else 0
    if neutral_count < max(5, 0.20 * len(rows)) or (
        runner_up and neutral_count < 1.5 * runner_up
    ) or not _has_sustained_band(rows, neutral, 2 * tolerance, cadence):
        return EleCalibrationSuggestions(
            None,
            None,
            None,
            "No clearly dominant sustained Ele value identifies neutral.",
        )

    centers = [_weighted_center(group) for group in groups]
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
            "Neutral is suggested, but no separated endpoint was sustained.",
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


def _has_sustained_band(
    rows,
    center: float,
    tolerance: float,
    cadence: float,
) -> bool:
    start = None
    previous = None
    for row in rows:
        if abs(row.ele - center) <= tolerance and (
            previous is None
            or (row.clock - previous).total_seconds() <= 2.5 * cadence
        ):
            start = row.clock if start is None else start
            if (row.clock - start).total_seconds() >= 1.0:
                return True
        else:
            start = row.clock if abs(row.ele - center) <= tolerance else None
        previous = row.clock
    return False


def _format_preview(
    source: Path,
    start: datetime,
    end: datetime,
    row_count: int,
    markers: tuple[LandmarkMarker, ...],
    direction: str,
    assessment: str,
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
        f"Direction used: {_direction_label(direction)}",
        f"Marker candidates: {len(markers)}",
        f"Direction assessment: {assessment}",
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


def _direction_label(direction: str) -> str:
    return "higher (+Ele)" if direction == "higher" else "lower (-Ele)"
