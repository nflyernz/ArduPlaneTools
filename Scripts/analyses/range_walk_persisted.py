"""Qt-independent persisted Range-Walk comparison service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyses.range_walk import format_range_walk_report, write_range_walk_graphs
from core.edgetx import read_edgetx_csv
from core.range_walk import WalkEvidence, interval_evidence, settings_comparable
from core.range_walk_history import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_HISTORY_PATH,
    RangeWalkHistoryError,
    RangeWalkHistoryStore,
    StoredAdditionalWalk,
    StoredWalk1Baseline,
)


COMPARISON_INTERPRETATION = (
    "A like-for-like comparison requires matching RF settings, valid landmark "
    "evidence, and consistent TX and RX antenna orientation and test conditions. "
    "Only the radio configuration being deliberately tested should change."
)


@dataclass(frozen=True)
class RangeWalkComparisonRequest:
    """Stable persisted identities selected for one background comparison."""

    baseline_id: str
    walk_ids: tuple[str, ...]
    output_dir: Path
    request_id: int


@dataclass(frozen=True)
class ComparedRangeWalk:
    """One stored record and its reconstructed RF evidence."""

    record: StoredWalk1Baseline | StoredAdditionalWalk
    evidence: WalkEvidence
    like_for_like: bool | None
    warning: str


@dataclass(frozen=True)
class RangeWalkComparisonResult:
    """Complete in-memory comparison returned to the GUI thread."""

    baseline: StoredWalk1Baseline
    walks: tuple[ComparedRangeWalk, ...]
    report: str
    graph_paths: tuple[Path, ...]
    request_id: int


class RangeWalkComparisonService:
    """Reload durable evidence and run the established comparison pipeline."""

    def __init__(
        self,
        *,
        history_path: str | Path = DEFAULT_HISTORY_PATH,
        evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
        store_factory=RangeWalkHistoryStore,
    ):
        self.history_path = Path(history_path)
        self.evidence_dir = Path(evidence_dir)
        self.store_factory = store_factory

    def compare(self, request: RangeWalkComparisonRequest) -> RangeWalkComparisonResult:
        if not request.walk_ids:
            raise ValueError("Select at least one additional walk")
        store = self.store_factory(self.history_path, self.evidence_dir)
        baselines, children = store.validated_history()
        baseline_by_id = {record.baseline_id: record for record in baselines}
        child_by_id = {record.walk_id: record for record in children}
        try:
            baseline = baseline_by_id[request.baseline_id]
        except KeyError as exc:
            raise RangeWalkHistoryError(
                f"Unknown Walk 1 baseline: {request.baseline_id}"
            ) from exc

        selected = []
        for walk_id in request.walk_ids:
            try:
                child = child_by_id[walk_id]
            except KeyError as exc:
                raise RangeWalkHistoryError(f"Unknown additional walk: {walk_id}") from exc
            if child.parent_baseline_id != baseline.baseline_id:
                raise RangeWalkHistoryError(
                    f"Walk {walk_id} is not associated with baseline "
                    f"{baseline.baseline_id}."
                )
            selected.append(child)

        baseline_evidence = _reconstruct_walk(baseline)
        compared = [ComparedRangeWalk(baseline, baseline_evidence, None, "")]
        evidences = [baseline_evidence]
        for child in selected:
            evidence = _reconstruct_walk(child)
            qualified = settings_comparable(baseline_evidence, evidence)
            warning = "" if qualified else "Like-for-like RF settings not established."
            compared.append(ComparedRangeWalk(child, evidence, qualified, warning))
            evidences.append(evidence)

        request.output_dir.mkdir(parents=True, exist_ok=True)
        landmarks = baseline.landmark_names
        report = format_range_walk_report(evidences, landmarks, baseline.turnaround)
        report += "\n\nInterpretation\n" + COMPARISON_INTERPRETATION
        paths = tuple(write_range_walk_graphs(evidences, landmarks, request.output_dir))
        return RangeWalkComparisonResult(
            baseline,
            tuple(compared),
            report,
            paths,
            request.request_id,
        )


def _reconstruct_walk(
    record: StoredWalk1Baseline | StoredAdditionalWalk,
) -> WalkEvidence:
    """Build evidence from persisted boundaries without detecting markers again."""
    session = read_edgetx_csv(record.stored_csv_path)
    landmarks = record.landmarks
    sections = tuple(
        interval_evidence(session, first.release, second.onset)
        if first is not None and second is not None and first.release < second.onset
        else None
        for first, second in zip(landmarks, landmarks[1:])
    )
    holds = tuple(
        interval_evidence(session, marker.onset, marker.release)
        if marker is not None and marker.onset < marker.release
        else None
        for marker in landmarks
    )
    return WalkEvidence(
        session,
        record.label,
        record.antenna,
        record.settings,
        record.candidates,
        landmarks,
        sections,
        holds,
    )
