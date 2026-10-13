"""Qt-independent Battery Pack Management operations."""

from dataclasses import dataclass
from pathlib import Path

from core.battery_pack_history import (
    DEFAULT_HISTORY_PATH,
    BatteryPackHistoryStore,
)
from core.battery_pack_history_recorder import BatteryPackHistoryRecorder
from core.battery_pack_store import (
    DEFAULT_STORE_PATH,
    BatteryPackStore,
    LogPackAssociation,
    LogPackState,
    fingerprint_log,
)
from core.config import Config
from core.log_reader import FlightReader


class StalePackManagementStateError(RuntimeError):
    """The confirmed source identity or association changed before mutation."""


@dataclass(frozen=True)
class PackManagementState:
    """Read-only persistent identity state for one selected BIN."""

    log_path: Path
    fingerprint: str
    association: LogPackAssociation
    pack_ids: tuple[str, ...]


@dataclass(frozen=True)
class PackManagementResult:
    """Completed management operation and refreshed persisted state."""

    state: PackManagementState
    message: str
    changed: bool
    observations_added: int | None = None
    selected_pack_id: str | None = None


class BatteryPackManagementService:
    """Expose explicit read and write operations over existing pack stores."""

    def __init__(
        self,
        *,
        pack_store_path: str | Path = DEFAULT_STORE_PATH,
        history_store_path: str | Path = DEFAULT_HISTORY_PATH,
        pack_store_factory=BatteryPackStore,
        history_store_factory=BatteryPackHistoryStore,
        config_factory=Config,
        reader_factory=FlightReader,
        recorder_factory=BatteryPackHistoryRecorder,
    ):
        self._pack_store_path = Path(pack_store_path)
        self._history_store_path = Path(history_store_path)
        self._pack_store_factory = pack_store_factory
        self._history_store_factory = history_store_factory
        self._config_factory = config_factory
        self._reader_factory = reader_factory
        self._recorder_factory = recorder_factory

    def lookup(self, log_path: Path) -> PackManagementState:
        """Hash one BIN and resolve its association without writing."""
        path = Path(log_path).resolve()
        fingerprint = fingerprint_log(path)
        store = self._pack_store()
        return self._state(path, fingerprint, store)

    def assign_existing(
        self,
        expected: PackManagementState,
        pack_id: str,
    ) -> PackManagementResult:
        """Assign the confirmed BIN identity to an existing Pack ID."""
        path, fingerprint, store = self._validated_context(expected)
        if (
            expected.association.state is LogPackState.TRACKED
            and expected.association.pack_id == pack_id.strip()
        ):
            return PackManagementResult(
                self._state(path, fingerprint, store),
                f"Pack assignment is already {pack_id.strip()}.",
                False,
            )
        store.associate(fingerprint, pack_id)
        reloaded = self._pack_store()
        return PackManagementResult(
            self._state(path, fingerprint, reloaded),
            f"Assigned {path.name} to Pack ID {pack_id.strip()}.",
            True,
        )

    def create_and_assign(
        self,
        expected: PackManagementState,
        pack_id: str,
    ) -> PackManagementResult:
        """Atomically create a Pack ID and assign the confirmed BIN."""
        path, fingerprint, store = self._validated_context(expected)
        store.create_and_associate(fingerprint, pack_id)
        normalized = pack_id.strip()
        reloaded = self._pack_store()
        return PackManagementResult(
            self._state(path, fingerprint, reloaded),
            f"Created Pack ID {normalized} and assigned {path.name}.",
            True,
        )

    def rename(
        self,
        expected: PackManagementState,
        old_pack_id: str,
        new_pack_id: str,
    ) -> PackManagementResult:
        """Rename a Pack ID globally after validating the confirmed BIN state."""
        path, fingerprint, store = self._validated_context(expected)
        if old_pack_id.strip() == new_pack_id.strip():
            return PackManagementResult(
                self._state(path, fingerprint, store),
                "Pack ID is unchanged.",
                False,
            )
        store.rename_pack(old_pack_id, new_pack_id)
        old_id = old_pack_id.strip()
        new_id = new_pack_id.strip()
        reloaded = self._pack_store()
        return PackManagementResult(
            self._state(path, fingerprint, reloaded),
            f"Renamed Pack ID {old_id} to {new_id} for all associated BINs.",
            True,
            selected_pack_id=new_id,
        )

    def record_history(
        self,
        expected: PackManagementState,
    ) -> PackManagementResult:
        """Explicitly ingest all supported AUTO takeoffs from a tracked BIN."""
        path, fingerprint, store = self._validated_context(expected)
        association = store.association_for(fingerprint)
        if (
            association.state is not LogPackState.TRACKED
            or association.pack_id is None
        ):
            raise StalePackManagementStateError(
                "The selected BIN no longer has a tracked Pack ID."
            )

        config = self._config_factory("Config/battery.yaml")
        flight_log = self._reader_factory(path, config=config).read()
        history_store = self._history_store_factory(self._history_store_path)
        added = self._recorder_factory(config).record(
            flight_log,
            path,
            fingerprint,
            association.pack_id,
            history_store,
        )
        refreshed = self._pack_store()
        noun = "observation" if added == 1 else "observations"
        return PackManagementResult(
            self._state(path, fingerprint, refreshed),
            f"Recorded {added} new AUTO takeoff {noun} from {path.name}.",
            added > 0,
            observations_added=added,
        )

    def _validated_context(
        self,
        expected: PackManagementState,
    ) -> tuple[Path, str, BatteryPackStore]:
        path = Path(expected.log_path).resolve()
        fingerprint = fingerprint_log(path)
        if fingerprint != expected.fingerprint:
            raise StalePackManagementStateError(
                "The selected BIN content changed after confirmation."
            )
        store = self._pack_store()
        if store.association_for(fingerprint) != expected.association:
            raise StalePackManagementStateError(
                "The selected BIN association changed after confirmation."
            )
        return path, fingerprint, store

    def _pack_store(self) -> BatteryPackStore:
        return self._pack_store_factory(self._pack_store_path)

    @staticmethod
    def _state(
        path: Path,
        fingerprint: str,
        store: BatteryPackStore,
    ) -> PackManagementState:
        return PackManagementState(
            log_path=path,
            fingerprint=fingerprint,
            association=store.association_for(fingerprint),
            pack_ids=store.pack_ids,
        )
