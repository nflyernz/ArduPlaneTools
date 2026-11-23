"""Qt-independent access to read-only Battery Pack Performance reports."""

from dataclasses import dataclass
from pathlib import Path

from analyses.battery import (
    format_pack_performance_report,
    open_pack_performance_histories,
)
from core.battery_pack_history import (
    DEFAULT_HISTORY_PATH,
    BatteryPackHistoryStore,
)
from core.battery_pack_history_protection import DEFAULT_V2_HISTORY_PATH
from core.battery_pack_history_v2 import BatteryPackHistoryV2Store
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
        v2_history_store_path: str | Path | None = None,
        pack_store_factory=BatteryPackStore,
        history_store_factory=BatteryPackHistoryStore,
        v2_history_store_factory=BatteryPackHistoryV2Store,
    ):
        self._pack_store_path = Path(pack_store_path)
        self._history_store_path = Path(history_store_path)
        self._v2_history_store_path = (Path(v2_history_store_path)
            if v2_history_store_path is not None else
            DEFAULT_V2_HISTORY_PATH if self._history_store_path == DEFAULT_HISTORY_PATH
            else self._history_store_path.with_name("battery_pack_history_v2.json"))
        self._pack_store_factory = pack_store_factory
        self._history_store_factory = history_store_factory
        self._v2_history_store_factory = v2_history_store_factory

    def refresh(self) -> PackPerformanceIndex:
        """Reload known packs and validate that stored history is readable."""
        pack_store = self._pack_store()
        self._histories()
        return PackPerformanceIndex(pack_store.pack_ids)

    def report(self, pack_id: str) -> PackPerformanceReport:
        """Return the shared CLI report for one currently known Pack ID."""
        pack_store = self._pack_store()
        history_store, v2_history_store = self._histories()
        return PackPerformanceReport(
            pack_id,
            format_pack_performance_report(
                pack_store,
                history_store,
                pack_id,
                v2_history_store,
            ),
        )

    def _pack_store(self):
        return self._pack_store_factory(self._pack_store_path)

    def _histories(self):
        return open_pack_performance_histories(
            self._pack_store_path, self._history_store_path,
            self._v2_history_store_path, self._history_store_factory,
            self._v2_history_store_factory,
        )
