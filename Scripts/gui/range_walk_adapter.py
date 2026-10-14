"""Qt-independent EdgeTX CSV marker preview for Range-Walk Comparison."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.edgetx import read_edgetx_csv
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
    )


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
