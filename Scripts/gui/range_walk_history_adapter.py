"""Qt-independent persistence service for Range-Walk GUI history."""

from dataclasses import dataclass
from pathlib import Path

from core.range_walk_history import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_HISTORY_PATH,
    RangeWalkHistoryStore,
    StoredAdditionalWalk,
    StoredWalk1Baseline,
)

from .range_walk_adapter import AdditionalWalk, Walk1Baseline


@dataclass(frozen=True)
class SaveWalk1Request:
    """One validated baseline persistence request tied to GUI evidence."""

    baseline: Walk1Baseline
    request_id: int


@dataclass(frozen=True)
class SavedWalk1Result:
    """Completed persistence result returned by the worker."""

    baseline: Walk1Baseline
    record: StoredWalk1Baseline
    request_id: int
    updated: bool


@dataclass(frozen=True)
class UpdateWalk1Request:
    """Metadata update guarded by the record originally shown to the GUI."""

    baseline: Walk1Baseline
    expected_record: StoredWalk1Baseline
    request_id: int


@dataclass(frozen=True)
class SaveAdditionalWalkRequest:
    """One later walk persistence request tied to its detected evidence."""

    walk: AdditionalWalk
    request_id: int


@dataclass(frozen=True)
class SavedAdditionalWalkResult:
    """Completed later-walk persistence result returned by the worker."""

    walk: AdditionalWalk
    record: StoredAdditionalWalk
    request_id: int


@dataclass(frozen=True)
class RangeWalkHistoryRequest:
    """Request a fresh validated history view."""

    request_id: int


@dataclass(frozen=True)
class RangeWalkHistoryResult:
    """Validated stored records and their presentation."""

    records: tuple[StoredWalk1Baseline, ...]
    walks: tuple[StoredAdditionalWalk, ...]
    request_id: int
    text: str


class RangeWalkHistoryService:
    """Create stores per operation so external changes are reloaded."""

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

    def save(self, request: SaveWalk1Request) -> SavedWalk1Result:
        """Persist one validated baseline and its original CSV evidence."""
        record = self._store().add_baseline(request.baseline)
        return SavedWalk1Result(request.baseline, record, request.request_id, False)

    def update(self, request: UpdateWalk1Request) -> SavedWalk1Result:
        """Update editable metadata without replacing preserved evidence."""
        record = self._store().update_baseline_metadata(
            request.expected_record.baseline_id,
            request.expected_record,
            request.baseline,
        )
        return SavedWalk1Result(request.baseline, record, request.request_id, True)

    def save_additional_walk(
        self, request: SaveAdditionalWalkRequest
    ) -> SavedAdditionalWalkResult:
        """Persist one additional walk and its original CSV evidence."""
        record = self._store().add_additional_walk(request.walk)
        return SavedAdditionalWalkResult(request.walk, record, request.request_id)

    def history(self, request: RangeWalkHistoryRequest) -> RangeWalkHistoryResult:
        """Reload and validate every durable baseline and managed CSV."""
        records, walks = self._store().validated_history()
        return RangeWalkHistoryResult(
            records,
            walks,
            request.request_id,
            format_range_walk_history(records, walks),
        )

    def _store(self):
        return self.store_factory(self.history_path, self.evidence_dir)


def format_range_walk_history(
    records: tuple[StoredWalk1Baseline, ...],
    walks: tuple[StoredAdditionalWalk, ...] = (),
) -> str:
    """Format saved Walk 1 records without suggesting completed comparisons."""
    lines = [
        "Range-Walk History & Comparison",
        "================================",
        "Saved baselines and associated later walks are read-only in this view.",
        "Comparisons are not yet available.",
        "RF performance comparisons, rankings and graphs remain deferred.",
    ]
    if not records:
        lines.extend(["", "No saved Walk 1 baselines."])
        return "\n".join(lines)
    for index, record in enumerate(records, start=1):
        lines.extend(
            [
                "",
                f"Walk 1 baseline {index}: {record.label}",
                f"  Baseline ID: {record.baseline_id}",
                f"  Baseline radio configuration: {record.antenna}",
                f"  Original CSV: {record.original_csv_filename}",
                "  Radio-local recording: "
                f"{record.recording_start.isoformat(sep=' ', timespec='seconds')}",
                f"  Saved at UTC: {record.created_at_utc}",
                f"  Preserved source CSV: Yes ({record.stored_csv_path.name})",
                "  Landmarks:",
            ]
        )
        for position, name in enumerate(record.landmark_names, start=1):
            suffix = " — turnaround" if position == 5 else ""
            lines.append(f"    {position}. {name}{suffix}")
        lines.extend(
            [
                "  Configured RF settings:",
                f"    TX power: {record.settings.tx_power or 'Unknown'}",
                f"    Packet rate: {record.settings.packet_rate or 'Unknown'}",
                f"    RF mode/band: {record.settings.rf_mode or 'Unknown'}",
                "    Dynamic TX power: "
                f"{record.settings.dynamic_power or 'Unknown'}",
            ]
        )
        if not all(
            (
                record.settings.tx_power,
                record.settings.packet_rate,
                record.settings.rf_mode,
                record.settings.dynamic_power,
            )
        ):
            lines.append(
                "  Warning: incomplete RF settings cannot support a later "
                "like-for-like comparison claim."
            )
        associated = [
            walk for walk in walks if walk.parent_baseline_id == record.baseline_id
        ]
        if not associated:
            lines.append("  Additional walks: None")
            continue
        lines.append("  Additional walks:")
        for walk in associated:
            lines.extend(_format_additional_walk(record, walk))
    return "\n".join(lines)


def _format_additional_walk(
    baseline: StoredWalk1Baseline,
    walk: StoredAdditionalWalk,
) -> list[str]:
    missing = [
        name
        for name, marker in zip(baseline.landmark_names, walk.landmarks)
        if marker is None
    ]
    lines = [
        f"    {walk.label}",
        f"      Walk ID: {walk.walk_id}",
        f"      Parent baseline: {walk.parent_baseline_id}",
        f"      Test radio configuration: {walk.antenna}",
        f"      Original CSV: {walk.original_csv_filename}",
        f"      Managed CSV SHA-256: {walk.csv_sha256}",
        f"      Preserved source CSV: {walk.stored_csv_path.name}",
        "      Radio-local recording: "
        f"{walk.recording_start.isoformat(sep=' ', timespec='seconds')} to "
        f"{walk.recording_end.isoformat(sep=' ', timespec='seconds')}",
        f"      Saved at UTC: {walk.created_at_utc}",
        f"      Confirmed landmarks: {walk.confirmed_landmark_count}/5",
        "      Missing landmarks: " + (", ".join(missing) if missing else "None"),
        f"      Available complete sections: {walk.complete_section_count}/4",
        "      Configured RF settings inherited from baseline:",
        f"        TX power: {walk.settings.tx_power or 'Unknown'}",
        f"        Packet rate: {walk.settings.packet_rate or 'Unknown'}",
        f"        RF mode/band: {walk.settings.rf_mode or 'Unknown'}",
        f"        Dynamic TX power: {walk.settings.dynamic_power or 'Unknown'}",
        "      Evidence integrity: managed CSV checksum validated",
    ]
    for position, (name, marker) in enumerate(
        zip(baseline.landmark_names, walk.landmarks), start=1
    ):
        status = "confirmed" if marker is not None else "missing marker evidence"
        lines.append(f"        Landmark {position} — {name}: {status}")
    return lines
