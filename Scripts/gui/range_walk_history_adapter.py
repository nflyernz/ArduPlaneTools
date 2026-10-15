"""Qt-independent persistence service for Range-Walk GUI baselines."""

from dataclasses import dataclass
from pathlib import Path

from core.range_walk_history import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_HISTORY_PATH,
    RangeWalkHistoryStore,
    StoredWalk1Baseline,
)

from .range_walk_adapter import Walk1Baseline


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


@dataclass(frozen=True)
class RangeWalkHistoryRequest:
    """Request a fresh validated history view."""

    request_id: int


@dataclass(frozen=True)
class RangeWalkHistoryResult:
    """Validated stored records and their presentation."""

    records: tuple[StoredWalk1Baseline, ...]
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
        return SavedWalk1Result(request.baseline, record, request.request_id)

    def history(self, request: RangeWalkHistoryRequest) -> RangeWalkHistoryResult:
        """Reload and validate every durable baseline and managed CSV."""
        records = self._store().validated_records()
        return RangeWalkHistoryResult(
            records,
            request.request_id,
            format_range_walk_history(records),
        )

    def _store(self):
        return self.store_factory(self.history_path, self.evidence_dir)


def format_range_walk_history(records: tuple[StoredWalk1Baseline, ...]) -> str:
    """Format saved Walk 1 records without suggesting completed comparisons."""
    lines = [
        "Range-Walk History & Comparison",
        "================================",
        "Saved Walk 1 baselines are read-only in this view.",
        "Comparisons are not yet available.",
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
                f"  Original antenna: {record.antenna}",
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
    return "\n".join(lines)
