"""Qt-independent access to read-only Battery Pack Performance reports."""

from dataclasses import dataclass
from pathlib import Path

from analyses.battery import format_pack_performance_report
from core.battery_pack_history import (
    DEFAULT_HISTORY_PATH,
    BatteryPackHistoryStore,
)
from core.battery_pack_store import DEFAULT_STORE_PATH, BatteryPackStore


@dataclass(frozen=True)
class PackPerformanceIndex:
    """Known physical packs loaded from persistent storage."""

    pack_ids: tuple[str, ...]


@dataclass(frozen=True)
class PackPerformanceReport:
    """A formatted report tied to its selected physical Pack ID."""

    pack_id: str
    text: str


class BatteryPackPerformanceService:
    """Read Pack Performance persistence without opening or changing a BIN."""

    def __init__(
        self,
        *,
        pack_store_path: str | Path = DEFAULT_STORE_PATH,
        history_store_path: str | Path = DEFAULT_HISTORY_PATH,
        pack_store_factory=BatteryPackStore,
        history_store_factory=BatteryPackHistoryStore,
    ):
        self._pack_store_path = Path(pack_store_path)
        self._history_store_path = Path(history_store_path)
        self._pack_store_factory = pack_store_factory
        self._history_store_factory = history_store_factory

    def refresh(self) -> PackPerformanceIndex:
        """Reload known packs and validate that stored history is readable."""
        pack_store = self._pack_store()
        self._history_store()
        return PackPerformanceIndex(pack_store.pack_ids)

    def report(self, pack_id: str) -> PackPerformanceReport:
        """Return the shared CLI report for one currently known Pack ID."""
        pack_store = self._pack_store()
        history_store = self._history_store()
        return PackPerformanceReport(
            pack_id,
            format_pack_performance_report(
                pack_store,
                history_store,
                pack_id,
            ),
        )

    def _pack_store(self):
        return self._pack_store_factory(self._pack_store_path)

    def _history_store(self):
        return self._history_store_factory(self._history_store_path)
