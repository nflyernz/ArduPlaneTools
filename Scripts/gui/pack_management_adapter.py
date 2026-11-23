"""Qt-independent Battery Pack Management operations."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from core.battery_pack_history import (
    DEFAULT_HISTORY_PATH,
    BatteryPackHistoryStore,
)
from core.battery_pack_history_protection import (
    DEFAULT_V2_HISTORY_PATH,
    CoordinatedHistory,
    recover_pending_deletion,
)
from core.battery_pack_history_recorder import BatteryPackHistoryRecorder
from core.battery_pack_history_v2 import BatteryPackHistoryV2Store
from core.battery_pack_store import (
    DEFAULT_STORE_PATH,
    BatteryPackStore,
    LogPackAssociation,
    LogPackState,
    PackDeletionPlan,
    fingerprint_log,
)
from core.config import Config
from core.log_reader import FlightReader


class StalePackManagementStateError(RuntimeError):
    """The confirmed source identity or association changed before mutation."""


@dataclass(frozen=True)
class PackManagementState:
    """Read-only pack state, optionally including one selected BIN."""

    log_path: Path | None
    fingerprint: str | None
    association: LogPackAssociation
    pack_ids: tuple[str, ...]
    archived_pack_ids: tuple[str, ...] = ()
    unused_pack_ids: tuple[str, ...] = ()
    pack_revision: str = ""


@dataclass(frozen=True)
class PackManagementResult:
    """Completed management operation and refreshed persisted state."""

    state: PackManagementState
    message: str
    changed: bool
    observations_added: int | None = None
    selected_pack_id: str | None = None


@dataclass(frozen=True)
class PackDeletionPreview:
    """Confirmed deletion scope and exact backing-store revisions."""

    plan: PackDeletionPlan
    pack_revision: str
    history_revision: str
    associated_logs: tuple["AssociatedLogDisplay", ...] = ()
    v2_history_revision: str = ""


@dataclass(frozen=True)
class AssociatedLogDisplay:
    """Display evidence for one authoritative log fingerprint."""

    fingerprint: str
    filenames: tuple[str, ...]
    observation_count: int


class BatteryPackManagementService:
    """Expose explicit read and write operations over existing pack stores."""

    def __init__(
        self,
        *,
        pack_store_path: str | Path = DEFAULT_STORE_PATH,
        history_store_path: str | Path = DEFAULT_HISTORY_PATH,
        v2_history_store_path: str | Path | None = None,
        pack_store_factory=BatteryPackStore,
        history_store_factory=BatteryPackHistoryStore,
        v2_history_store_factory=BatteryPackHistoryV2Store,
        config_factory=Config,
        reader_factory=FlightReader,
        recorder_factory=BatteryPackHistoryRecorder,
    ):
        self._pack_store_path = Path(pack_store_path)
        self._history_store_path = Path(history_store_path)
        self._v2_history_store_path = Path(v2_history_store_path) if v2_history_store_path is not None else (
            DEFAULT_V2_HISTORY_PATH if self._history_store_path == DEFAULT_HISTORY_PATH
            else self._history_store_path.with_name("battery_pack_history_v2.json")
        )
        self._pack_store_factory = pack_store_factory
        self._history_store_factory = history_store_factory
        self._v2_history_store_factory = v2_history_store_factory
        self._config_factory = config_factory
        self._reader_factory = reader_factory
        self._recorder_factory = recorder_factory

    def lookup(self, log_path: Path) -> PackManagementState:
        """Hash one BIN and resolve its association without writing."""
        path = Path(log_path).resolve()
        fingerprint = fingerprint_log(path)
        store = self._pack_store()
        return self._state(path, fingerprint, store)

    def lookup_packs(self) -> PackManagementState:
        """Load Pack IDs without selecting or hashing a BIN."""
        return self._state(None, None, self._pack_store())

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
        store.associate(fingerprint, pack_id, path.name)
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
        store.create_and_associate(fingerprint, pack_id, path.name)
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
        store = self._validated_pack_context(expected)
        if old_pack_id.strip() == new_pack_id.strip():
            return PackManagementResult(
                self._state(expected.log_path, expected.fingerprint, store),
                "Pack ID is unchanged.",
                False,
            )
        store.rename_pack(old_pack_id, new_pack_id)
        old_id = old_pack_id.strip()
        new_id = new_pack_id.strip()
        reloaded = self._pack_store()
        return PackManagementResult(
            self._state(expected.log_path, expected.fingerprint, reloaded),
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

    def archive(self, expected: PackManagementState, pack_id: str) -> PackManagementResult:
        """Retire a pack from new assignments without changing its evidence."""
        store = self._validated_pack_context(expected)
        store.archive_pack(pack_id)
        return PackManagementResult(self._state(expected.log_path, expected.fingerprint, self._pack_store()),
                                    f"Archived Pack ID {pack_id}.", True)

    def restore(self, expected: PackManagementState, pack_id: str) -> PackManagementResult:
        """Return an archived pack to normal selection."""
        store = self._validated_pack_context(expected)
        store.restore_pack(pack_id)
        return PackManagementResult(self._state(expected.log_path, expected.fingerprint, self._pack_store()),
                                    f"Restored Pack ID {pack_id}.", True)

    def preview_delete(self, expected: PackManagementState, pack_id: str) -> PackDeletionPreview:
        """Read the impact of deletion without changing either store."""
        store = self._validated_pack_context(expected)
        history = self._history_context()
        plan = store.deletion_plan(pack_id, history)
        associated_logs = []
        for fingerprint in plan.log_fingerprints:
            names = list(store.known_filenames_for(fingerprint))
            for observation in history.observations:
                name = observation.source_filename
                if (observation.source_sha256 == fingerprint and name
                        and name == Path(name).name and "\\" not in name
                        and name not in names):
                    names.append(name)
            associated_logs.append(AssociatedLogDisplay(
                fingerprint, tuple(names),
                sum(observation.source_sha256 == fingerprint
                    and observation.observation_id in (*plan.observation_ids, *plan.v2_observation_ids)
                    for observation in history.observations),
            ))
        return PackDeletionPreview(
            plan,
            self._revision(self._pack_store_path),
            self._revision(self._history_store_path),
            tuple(associated_logs),
            self._revision(self._v2_history_store_path),
        )

    def delete(
        self, expected: PackManagementState, pack_id: str,
        preview: PackDeletionPreview | None = None,
    ) -> PackManagementResult:
        """Permanently remove exactly the confirmed pack and history."""
        current = self.preview_delete(expected, pack_id)
        if preview is not None and current != preview:
            raise StalePackManagementStateError(
                "Pack associations or history changed after confirmation; refresh and try again."
            )
        store = self._validated_pack_context(expected)
        history = self._history_context()
        plan = store.delete_pack(pack_id, history, current.plan)
        return PackManagementResult(self._state(expected.log_path, expected.fingerprint, self._pack_store()),
                                    f"Deleted Pack ID {pack_id}; marked {len(plan.log_fingerprints)} "
                                    f"BIN logs Not tracked and removed {len(plan.observation_ids)} v1 and "
                                    f"{len(plan.v2_observation_ids)} v2 history observations.", True)

    @staticmethod
    def _revision(path: Path) -> str:
        if not path.exists():
            return "missing"
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _validated_context(
        self,
        expected: PackManagementState,
    ) -> tuple[Path, str, BatteryPackStore]:
        if expected.log_path is None or expected.fingerprint is None:
            raise StalePackManagementStateError("Select a BIN log for this action.")
        path = expected.log_path.resolve()
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

    def _validated_pack_context(self, expected: PackManagementState) -> BatteryPackStore:
        store = self._pack_store()
        if (store.active_pack_ids != expected.pack_ids
                or store.archived_pack_ids != expected.archived_pack_ids
                or self._revision(self._pack_store_path) != expected.pack_revision):
            raise StalePackManagementStateError(
                "Pack IDs or associations changed; refresh and try again."
            )
        return store

    def _pack_store(self) -> BatteryPackStore:
        recover_pending_deletion(self._pack_store_path, self._history_store_path,
                                 self._v2_history_store_path)
        return self._pack_store_factory(self._pack_store_path)

    def _history_context(self) -> CoordinatedHistory:
        return CoordinatedHistory(
            self._pack_store_path, self._history_store_path, self._v2_history_store_path,
            self._history_store_factory, self._v2_history_store_factory,
        )

    def _state(
        self,
        path: Path | None,
        fingerprint: str | None,
        store: BatteryPackStore,
    ) -> PackManagementState:
        history_store = self._history_context()
        return PackManagementState(
            log_path=path,
            fingerprint=fingerprint,
            association=(store.association_for(fingerprint) if fingerprint is not None
                         else LogPackAssociation(LogPackState.UNSEEN)),
            pack_ids=store.active_pack_ids,
            archived_pack_ids=store.archived_pack_ids,
            unused_pack_ids=store.unused_pack_ids(history_store),
            pack_revision=self._revision(self._pack_store_path),
        )
