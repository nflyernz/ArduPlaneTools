"""Qt-independent comparison of checksum-managed Range-Walk history."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from analyses.range_walk import format_range_walk_report, write_range_walk_graphs
from core.edgetx import read_edgetx_csv
from core.range_walk import IntervalEvidence, build_walk_from_landmarks
from core.range_walk_history import (
    RangeWalkHistoryError,
    RangeWalkHistoryStore,
    StoredAdditionalWalk,
    StoredWalk1Baseline,
)


@dataclass(frozen=True)
class RangeWalkComparisonRequest:
    """One saved baseline/additional-walk comparison request."""

    baseline_id: str
    walk_id: str
    request_id: int


@dataclass(frozen=True)
class RangeWalkSectionRow:
    """Presentation-ready identity plus authoritative section evidence."""

    section: str
    walk: str
    evidence: IntervalEvidence | None
    status: str


@dataclass(frozen=True)
class RangeWalkPlot:
    """One existing comparison PNG returned without worker-owned Qt objects."""

    filename: str
    title: str
    data: bytes


@dataclass(frozen=True)
class RangeWalkComparisonResult:
    """Complete read-only comparison result for the GUI."""

    baseline: StoredWalk1Baseline
    walk: StoredAdditionalWalk
    request_id: int
    rows: tuple[RangeWalkSectionRow, ...]
    qualification: str
    report: str
    details: str
    plots: tuple[RangeWalkPlot, ...]


def compare_saved_range_walks(
    request: RangeWalkComparisonRequest,
    store: RangeWalkHistoryStore,
) -> RangeWalkComparisonResult:
    """Rebuild the existing comparison solely from validated managed evidence."""
    baselines, walks = store.validated_history()
    baseline = next(
        (item for item in baselines if item.baseline_id == request.baseline_id),
        None,
    )
    if baseline is None:
        raise RangeWalkHistoryError(
            f"Saved Walk 1 baseline is unavailable: {request.baseline_id}"
        )
    walk = next((item for item in walks if item.walk_id == request.walk_id), None)
    if walk is None:
        raise RangeWalkHistoryError(
            f"Saved comparison walk is unavailable: {request.walk_id}"
        )
    if walk.parent_baseline_id != baseline.baseline_id:
        raise RangeWalkHistoryError(
            "Selected comparison walk does not belong to the selected baseline."
        )

    baseline_evidence = _walk_evidence(baseline)
    comparison_evidence = _walk_evidence(walk)
    evidence = [baseline_evidence, comparison_evidence]
    rows = tuple(
        RangeWalkSectionRow(
            f"{index + 1}→{index + 2}",
            role,
            item.sections[index],
            _section_status(item.sections[index], inherited=inherited),
        )
        for index in range(4)
        for item, role, inherited in (
            (baseline_evidence, "Walk 1 baseline", False),
            (comparison_evidence, "Comparison walk", True),
        )
    )
    qualification = _qualification(baseline, walk)
    report = format_range_walk_report(
        evidence, baseline.landmark_names, baseline.turnaround
    )
    with TemporaryDirectory(prefix="apt-range-walk-") as directory:
        paths = write_range_walk_graphs(
            evidence, baseline.landmark_names, Path(directory)
        )
        plots = tuple(
            RangeWalkPlot(path.name, _plot_title(path.name), path.read_bytes())
            for path in paths
        )
    details = (
        qualification
        + "\n\n"
        + report
        + "\n\nSaved evidence metadata\n"
        + "=======================\n"
        + _saved_metadata(baseline, walk)
    )
    return RangeWalkComparisonResult(
        baseline,
        walk,
        request.request_id,
        rows,
        qualification,
        report,
        details,
        plots,
    )


def _walk_evidence(record):
    session = read_edgetx_csv(record.stored_csv_path)
    return build_walk_from_landmarks(
        session,
        record.label,
        record.antenna,
        record.settings,
        record.candidates,
        record.landmarks,
    )


def _section_status(
    evidence: IntervalEvidence | None, *, inherited: bool
) -> str:
    if evidence is None:
        return "Incomplete marker boundary"
    if evidence.median_values["1RSS(dB)"] is None:
        return "Unavailable RF evidence"
    return "Observed; settings inherited" if inherited else "Observed"


def _qualification(
    baseline: StoredWalk1Baseline, walk: StoredAdditionalWalk
) -> str:
    return "\n".join(
        (
            "Saved Range-Walk RF comparison",
            f"Baseline configuration: {baseline.antenna}",
            f"Comparison configuration: {walk.antenna}",
            "Qualification: later-walk RF settings are inherited from Walk 1 "
            "and are not independently verified for that recording.",
            "Coverage is eligible logged observation time, not proof of "
            "continuous receiver reception or independent RF updates.",
            "Missing telemetry is unavailable evidence, not zero RF signal.",
            "All RF values come from transmitter EdgeTX CSV evidence; aircraft "
            "BIN failsafe evidence is separate.",
            "No automatic antenna winner is declared.",
        )
    )


def _plot_title(filename: str) -> str:
    if filename == "walk_1_rf.png":
        return "Walk 1 RF"
    if filename == "walk_2_rf.png":
        return "Comparison walk RF"
    return "Section RSSI and RQly P10 comparison"


def _saved_metadata(
    baseline: StoredWalk1Baseline, walk: StoredAdditionalWalk
) -> str:
    settings = baseline.settings
    return "\n".join(
        (
            f"Walk 1 ID: {baseline.baseline_id}",
            f"  Original CSV: {baseline.original_csv_filename}",
            f"  Managed CSV: {baseline.stored_csv_path}",
            f"  SHA-256: {baseline.csv_sha256}",
            f"  Radio configuration: {baseline.antenna}",
            f"Comparison walk ID: {walk.walk_id}",
            f"  Parent baseline: {walk.parent_baseline_id}",
            f"  Original CSV: {walk.original_csv_filename}",
            f"  Managed CSV: {walk.stored_csv_path}",
            f"  SHA-256: {walk.csv_sha256}",
            f"  Radio configuration: {walk.antenna}",
            "Inherited RF settings:",
            f"  TX power: {settings.tx_power or 'Unknown'}",
            f"  Packet rate: {settings.packet_rate or 'Unknown'}",
            f"  RF mode/band: {settings.rf_mode or 'Unknown'}",
            f"  Dynamic TX power: {settings.dynamic_power or 'Unknown'}",
            "Landmarks: " + " → ".join(baseline.landmark_names),
        )
    )
