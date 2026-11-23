"""Persistent physical battery Pack IDs and source-log associations."""

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .application_data import application_data_directory
from .battery_pack_history import (
    DEFAULT_HISTORY_PATH,
    BatteryPackHistoryStore,
    BatteryPackObservation,
)

SCHEMA_VERSION = 5
DEFAULT_STORE_PATH = application_data_directory() / "battery_packs.json"


class BatteryPackStoreError(ValueError):
    """Base error for invalid battery-pack persistence operations."""


class BatteryPackStoreFormatError(BatteryPackStoreError):
    """Persistent battery-pack data does not match the supported schema."""


class LogPackState(Enum):
    """Persistent tracking decision for one source-log fingerprint."""

    UNSEEN = "unseen"
    TRACKED = "tracked"
    NOT_TRACKED = "not_tracked"


@dataclass(frozen=True)
class LogPackAssociation:
    """Resolved persistent tracking state for one source log."""

    state: LogPackState
    pack_id: str | None = None


@dataclass(frozen=True)
class PackDeletionPlan:
    """Exact persisted references affected by deleting one pack."""

    pack_id: str
    log_fingerprints: tuple[str, ...]
    observation_ids: tuple[str, ...]
    retained_history_owners: tuple[tuple[str, str], ...] = ()
    v2_observation_ids: tuple[str, ...] = ()
    store_revisions: tuple[str, str, str] | None = None


def fingerprint_log(log_path: str | Path) -> str:
    """Return the SHA-256 content identity of one BIN file."""
    digest = hashlib.sha256()
    with Path(log_path).open("rb") as log_file:
        for chunk in iter(lambda: log_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BatteryPackStore:
    """Small versioned JSON store for Pack IDs and log decisions."""

    def __init__(self, path: str | Path = DEFAULT_STORE_PATH):
        self.path = Path(path)
        self._pack_ids: list[str] = []
        self._archived_pack_ids: list[str] = []
        self._associations: dict[str, LogPackAssociation] = {}
        self._history_owners: dict[str, str] = {}
        self._pack_aliases: dict[str, str] = {}
        self._log_filenames: dict[str, tuple[str, ...]] = {}
        self._load()
        self._loaded_revision = self._file_revision()

    def _file_revision(self) -> str:
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return "missing"

    @property
    def pack_ids(self) -> tuple[str, ...]:
        """Return all physical Pack IDs, including archived ones, for reports."""
        return tuple(self._pack_ids)

    @property
    def active_pack_ids(self) -> tuple[str, ...]:
        """Return Pack IDs eligible for new log assignments."""
        return tuple(pack for pack in self._pack_ids if pack not in self._archived_pack_ids)

    @property
    def archived_pack_ids(self) -> tuple[str, ...]:
        """Return archived Pack IDs in creation order."""
        return tuple(pack for pack in self._pack_ids if pack in self._archived_pack_ids)

    def unused_pack_ids(self, history_store: object) -> tuple[str, ...]:
        """Return active and archived packs with no saved evidence."""
        history_store = self._protected_history(history_store)
        return tuple(
            pack for pack in self._pack_ids
            if self._deletion_blocker(pack, history_store) is None
        )

    def association_for(self, fingerprint: str) -> LogPackAssociation:
        """Return the stored decision, or explicit unseen state."""
        self._validate_fingerprint(fingerprint)
        return self._associations.get(
            fingerprint,
            LogPackAssociation(LogPackState.UNSEEN),
        )

    def retained_history_owner_for(self, observation_id: str) -> str | None:
        """Return a preserved owner for history after its log became untracked."""
        return self._history_owners.get(observation_id)

    def history_owner_for(self, observation: BatteryPackObservation) -> str | None:
        """Resolve immutable ingest provenance through explicit retained owners and renames."""
        ingest = observation.pack_id_at_ingest
        owner = self._history_owners.get(
            observation.observation_id, self._pack_aliases.get(ingest, ingest),
        )
        return owner if owner in self._pack_ids else None

    def known_filenames_for(self, fingerprint: str) -> tuple[str, ...]:
        """Return display-only names recorded for this exact SHA-256 identity."""
        self._validate_fingerprint(fingerprint)
        return self._log_filenames.get(fingerprint, ())

    def associated_fingerprints(self, pack_id: str) -> tuple[str, ...]:
        """Return every tracked source identity assigned to one Pack ID."""
        pack = self._require_pack(pack_id)
        return tuple(sorted(
            fingerprint for fingerprint, association in self._associations.items()
            if association.pack_id == pack
        ))

    def associate(
        self, fingerprint: str, pack_id: str,
        source_filename: str | None = None,
    ) -> None:
        """Associate a source log with an existing Pack ID."""
        self._validate_fingerprint(fingerprint)
        normalized_id = self._normalize_pack_id(pack_id)
        if normalized_id not in self.active_pack_ids:
            raise BatteryPackStoreError(f"Unknown Pack ID: {normalized_id}")
        associations = dict(self._associations)
        associations[fingerprint] = LogPackAssociation(
            LogPackState.TRACKED,
            normalized_id,
        )
        self._save(self._pack_ids, associations,
                   log_filenames=self._with_filename(fingerprint, source_filename))

    def create_and_associate(
        self, fingerprint: str, pack_id: str,
        source_filename: str | None = None,
    ) -> None:
        """Create one Pack ID and associate the source log atomically."""
        self._validate_fingerprint(fingerprint)
        normalized_id = self._normalize_pack_id(pack_id)
        if normalized_id in self._pack_aliases:
            raise BatteryPackStoreError(
                f"Pack ID {normalized_id} is reserved by retained history."
            )
        if normalized_id in self._pack_ids:
            raise BatteryPackStoreError(f"Pack ID already exists: {normalized_id}")
        pack_ids = [*self._pack_ids, normalized_id]
        associations = dict(self._associations)
        associations[fingerprint] = LogPackAssociation(
            LogPackState.TRACKED,
            normalized_id,
        )
        self._save(pack_ids, associations,
                   log_filenames=self._with_filename(fingerprint, source_filename))

    def mark_not_tracked(
        self, fingerprint: str, source_filename: str | None = None,
    ) -> None:
        """Persist an explicit decision not to track this source log."""
        self._validate_fingerprint(fingerprint)
        associations = dict(self._associations)
        associations[fingerprint] = LogPackAssociation(LogPackState.NOT_TRACKED)
        self._save(self._pack_ids, associations,
                   log_filenames=self._with_filename(fingerprint, source_filename))

    def _with_filename(
        self, fingerprint: str, source_filename: str | None,
    ) -> dict[str, tuple[str, ...]]:
        names = dict(self._log_filenames)
        if source_filename is not None:
            self._validate_filename(source_filename)
            names[fingerprint] = tuple(dict.fromkeys((*names.get(fingerprint, ()),
                                                      source_filename)))
        return names

    def rename_pack(self, old_pack_id: str, new_pack_id: str) -> None:
        """Rename a Pack ID and update all matching associations atomically."""
        old_id = self._normalize_pack_id(old_pack_id)
        new_id = self._normalize_pack_id(new_pack_id)

        if old_id not in self._pack_ids:
            raise BatteryPackStoreError(f"Unknown Pack ID: {old_id}")

        if new_id == old_id:
            return

        if new_id in self._pack_ids:
            raise BatteryPackStoreError(f"Pack ID already exists: {new_id}")
        if new_id in self._pack_aliases:
            raise BatteryPackStoreError(
                f"Pack ID {new_id} is reserved by retained history."
            )

        pack_ids = [
            new_id if pack_id == old_id else pack_id
            for pack_id in self._pack_ids
        ]

        associations = {
            fingerprint: (
                LogPackAssociation(
                    LogPackState.TRACKED,
                    new_id,
                )
                if association.state is LogPackState.TRACKED
                and association.pack_id == old_id
                else association
            )
            for fingerprint, association in self._associations.items()
        }

        archived = [new_id if pack == old_id else pack for pack in self._archived_pack_ids]
        history_owners = {
            observation_id: new_id if owner == old_id else owner
            for observation_id, owner in self._history_owners.items()
        }
        aliases = {
            historical: new_id if owner == old_id else owner
            for historical, owner in self._pack_aliases.items()
        }
        aliases[old_id] = new_id
        self._save(pack_ids, associations, archived, history_owners,
                   pack_aliases=aliases)

    def archive_pack(self, pack_id: str) -> None:
        """Hide a pack from new assignments while preserving its history."""
        pack = self._require_pack(pack_id)
        if pack not in self._archived_pack_ids:
            self._save(self._pack_ids, self._associations, [*self._archived_pack_ids, pack])

    def restore_pack(self, pack_id: str) -> None:
        """Make an archived pack eligible for new assignments again."""
        pack = self._require_pack(pack_id)
        if pack in self._archived_pack_ids:
            self._save(self._pack_ids, self._associations,
                       [item for item in self._archived_pack_ids if item != pack])

    def deletion_plan(self, pack_id: str, history_store: object) -> PackDeletionPlan:
        """Resolve observation ownership from durable ingest or retained provenance."""
        history_store = self._protected_history(history_store)
        pack = self._require_pack(pack_id)
        fingerprints = tuple(sorted(
            fingerprint for fingerprint, association in self._associations.items()
            if association.pack_id == pack
        ))
        from .battery_pack_history_protection import CoordinatedHistory, revision

        coordinated = isinstance(history_store, CoordinatedHistory)
        if coordinated and (self._loaded_revision != self._file_revision()
                            or history_store.revisions != (
                                revision(history_store.v1.path),
                                revision(history_store.v2.path))):
            raise BatteryPackStoreError("Pack or history changed after loading; refresh and retry.")
        v1 = history_store.v1 if coordinated else history_store
        v2 = history_store.v2 if coordinated else None
        observations = []
        v2_observations = []
        retained_owners = []
        for version, rows in (("v1", v1.observations),
                              ("v2", v2.observations if v2 else ())):
            for observation in rows:
                association = self.association_for(observation.source_sha256)
                owner = self.history_owner_for(observation)
                if owner == pack:
                    (v2_observations if version == "v2" else observations).append(
                        observation.observation_id
                    )
                elif association.pack_id == pack:
                    if owner not in self._pack_ids:
                        raise BatteryPackStoreError(
                            f"Cannot delete Pack ID {pack}: observation "
                            f"{observation.observation_id} records Pack ID "
                            f"{observation.pack_id_at_ingest}, "
                            "which no longer exists. Restore that Pack ID or resolve "
                            "the historical record, then retry."
                        )
                    retained_owners.append((observation.observation_id, owner))
                elif owner is None:
                    raise BatteryPackStoreError(
                        f"Observation {observation.observation_id} has no surviving Pack ID owner."
                    )
        return PackDeletionPlan(
            pack, fingerprints, tuple(sorted(observations)),
            tuple(sorted(retained_owners)), tuple(sorted(v2_observations)),
            (revision(self.path), revision(v1.path), revision(v2.path)) if coordinated else None,
        )

    def delete_pack(
        self, pack_id: str, history_store: object,
        expected_plan: PackDeletionPlan | None = None,
    ) -> PackDeletionPlan:
        """Delete a pack and its history, rolling back if either write fails."""
        from .battery_pack_history_protection import (
            CoordinatedHistory,
            delete_coordinated,
        )

        history_store = self._protected_history(history_store)
        if isinstance(history_store, CoordinatedHistory):
            return delete_coordinated(self, history_store, pack_id, expected_plan)
        plan = self.deletion_plan(pack_id, history_store)
        if expected_plan is not None and plan != expected_plan:
            raise BatteryPackStoreError(
                "Pack associations or history changed after confirmation."
            )
        associations = dict(self._associations)
        for fingerprint in plan.log_fingerprints:
            associations[fingerprint] = LogPackAssociation(LogPackState.NOT_TRACKED)
        remaining = {
            observation.observation_id: observation
            for observation in history_store.observations
            if observation.observation_id not in plan.observation_ids
        }
        history_owners = {
            observation_id: owner
            for observation_id, owner in self._history_owners.items()
            if observation_id not in plan.observation_ids
        }
        history_owners.update(plan.retained_history_owners)
        aliases = {
            historical: owner
            for historical, owner in self._pack_aliases.items()
            if owner != plan.pack_id
        }
        backups: dict[Path, Path] = {}
        history_existed = history_store.path.exists()
        retain_backups = False
        try:
            for path in (self.path, history_store.path):
                if not path.exists():
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(
                    dir=path.parent,
                    prefix=f".{path.name}.", suffix=".backup",
                )
                os.close(descriptor)
                backups[path] = Path(name)
                shutil.copy2(path, backups[path])
            try:
                if plan.observation_ids:
                    history_store._save(remaining)
                self._save(
                    [item for item in self._pack_ids if item != plan.pack_id],
                    associations,
                    [item for item in self._archived_pack_ids if item != plan.pack_id],
                    history_owners,
                    pack_aliases=aliases,
                )
            except Exception:
                try:
                    for path, backup in backups.items():
                        if not path.exists() or path.read_bytes() != backup.read_bytes():
                            os.replace(backup, path)
                    if plan.observation_ids and not history_existed:
                        history_store.path.unlink(missing_ok=True)
                    self._load()
                    if history_existed:
                        history_store._load()
                except OSError as rollback_error:
                    retain_backups = True
                    locations = ", ".join(str(path) for path in backups.values())
                    raise BatteryPackStoreError(
                        f"Deletion rollback failed; backups retained at {locations}."
                    ) from rollback_error
                raise
        finally:
            if not retain_backups:
                for backup in backups.values():
                    backup.unlink(missing_ok=True)
        return plan

    def _protected_history(self, history_store: object) -> object:
        """Require both stores for application data or an existing sibling v2 store."""
        from .battery_pack_history_protection import (
            DEFAULT_V2_HISTORY_PATH,
            CoordinatedHistory,
            journal_path,
        )
        from .battery_pack_history_v2 import BatteryPackHistoryV2Store

        if isinstance(history_store, CoordinatedHistory):
            if history_store.pack_path.resolve() != self.path.resolve():
                raise BatteryPackStoreError(
                    "Coordinated history belongs to a different Pack Store."
                )
            return history_store
        if isinstance(history_store, BatteryPackHistoryV2Store):
            v1_path = history_store.path.with_name("battery_pack_history.json")
            if (v1_path.exists() or v1_path.is_symlink()
                    or journal_path(self.path).exists()
                    or self.path == DEFAULT_STORE_PATH
                    or history_store.path == DEFAULT_V2_HISTORY_PATH):
                return CoordinatedHistory(self.path, v1_path, history_store.path)
            return history_store
        if not isinstance(history_store, BatteryPackHistoryStore):
            raise BatteryPackStoreError("A Battery Pack History store is required.")
        v2_path = history_store.path.with_name("battery_pack_history_v2.json")
        if (v2_path.exists() or v2_path.is_symlink()
                or journal_path(self.path).exists()
                or self.path == DEFAULT_STORE_PATH
                or history_store.path == DEFAULT_HISTORY_PATH):
            return CoordinatedHistory(self.path, history_store.path, v2_path)
        return history_store

    def _deletion_blocker(self, pack_id: str, history_store: object) -> str | None:
        if any(a.pack_id == pack_id for a in self._associations.values()):
            return "Pack ID has log associations and cannot be deleted."
        if any(
            self.history_owner_for(observation) == pack_id
            or self._associations.get(
                observation.source_sha256,
                LogPackAssociation(LogPackState.UNSEEN),
            ).pack_id == pack_id
            for observation in history_store.observations
        ):
            return "Pack ID has historical observations and cannot be deleted."
        return None

    def _require_pack(self, pack_id: str) -> str:
        pack = self._normalize_pack_id(pack_id)
        if pack not in self._pack_ids:
            raise BatteryPackStoreError(f"Unknown Pack ID: {pack}")
        return pack

    def _load(self) -> None:
        if not self.path.exists():
            self._loaded_revision = "missing"
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BatteryPackStoreFormatError(
                f"Unable to read {self.path}: {exc}"
            ) from exc
        (self._pack_ids, self._associations, self._archived_pack_ids,
         self._history_owners, self._log_filenames,
         self._pack_aliases) = self._validate_data(data)
        self._loaded_revision = self._file_revision()

    def _save(
        self,
        pack_ids: list[str],
        associations: dict[str, LogPackAssociation],
        archived_pack_ids: list[str] | None = None,
        history_owners: dict[str, str] | None = None,
        log_filenames: dict[str, tuple[str, ...]] | None = None,
        pack_aliases: dict[str, str] | None = None,
    ) -> None:
        archived_pack_ids = list(self._archived_pack_ids if archived_pack_ids is None else archived_pack_ids)
        history_owners = dict(self._history_owners if history_owners is None else history_owners)
        log_filenames = dict(self._log_filenames if log_filenames is None else log_filenames)
        pack_aliases = dict(self._pack_aliases if pack_aliases is None else pack_aliases)
        data = {
            "version": SCHEMA_VERSION,
            "pack_ids": pack_ids,
            "archived_pack_ids": archived_pack_ids,
            "retained_history_owners": dict(sorted(history_owners.items())),
            "pack_aliases": dict(sorted(pack_aliases.items())),
            "log_filenames": {
                fingerprint: list(names)
                for fingerprint, names in sorted(log_filenames.items())
            },
            "log_associations": {
                fingerprint: (
                    {"state": association.state.value, "pack_id": association.pack_id}
                    if association.state is LogPackState.TRACKED
                    else {"state": association.state.value}
                )
                for fingerprint, association in sorted(associations.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as store_file:
                json.dump(data, store_file, indent=2)
                store_file.write("\n")
                store_file.flush()
                os.fsync(store_file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        self._pack_ids = list(pack_ids)
        self._associations = associations
        self._archived_pack_ids = archived_pack_ids
        self._history_owners = history_owners
        self._log_filenames = log_filenames
        self._pack_aliases = pack_aliases
        self._loaded_revision = self._file_revision()

    @classmethod
    def _validate_data(
        cls,
        data: object,
    ) -> tuple[
        list[str], dict[str, LogPackAssociation], list[str], dict[str, str],
        dict[str, tuple[str, ...]], dict[str, str],
    ]:
        if not isinstance(data, dict):
            raise BatteryPackStoreFormatError("Battery-pack store must be an object.")
        version = data.get("version")
        expected = {"version", "pack_ids", "log_associations"}
        if version in (2, 3, 4, SCHEMA_VERSION):
            expected.add("archived_pack_ids")
        if version in (3, 4, SCHEMA_VERSION):
            expected.add("retained_history_owners")
        if version in (4, SCHEMA_VERSION):
            expected.add("log_filenames")
        if version == SCHEMA_VERSION:
            expected.add("pack_aliases")
        if set(data) != expected:
            raise BatteryPackStoreFormatError(
                "Battery-pack store contains unexpected or missing fields."
            )
        if isinstance(version, bool) or not isinstance(version, int):
            raise BatteryPackStoreFormatError(
                "Battery-pack version must be an integer."
            )
        if version not in (1, 2, 3, 4, SCHEMA_VERSION):
            raise BatteryPackStoreFormatError(
                f"Unsupported battery-pack store version: {version}"
            )

        raw_pack_ids = data["pack_ids"]
        if not isinstance(raw_pack_ids, list):
            raise BatteryPackStoreFormatError("pack_ids must be a list.")
        pack_ids = []
        for pack_id in raw_pack_ids:
            try:
                normalized_id = cls._normalize_pack_id(pack_id)
            except BatteryPackStoreError as exc:
                raise BatteryPackStoreFormatError(str(exc)) from exc
            if normalized_id in pack_ids:
                raise BatteryPackStoreFormatError(f"Duplicate Pack ID: {normalized_id}")
            pack_ids.append(normalized_id)

        raw_associations = data["log_associations"]
        if not isinstance(raw_associations, dict):
            raise BatteryPackStoreFormatError("log_associations must be an object.")
        associations = {}
        for fingerprint, raw_association in raw_associations.items():
            try:
                cls._validate_fingerprint(fingerprint)
            except BatteryPackStoreError as exc:
                raise BatteryPackStoreFormatError(str(exc)) from exc
            associations[fingerprint] = cls._validate_association(
                raw_association,
                pack_ids,
            )
        raw_archived = data.get("archived_pack_ids", [])
        if (not isinstance(raw_archived, list) or
                any(not isinstance(pack, str) or pack not in pack_ids for pack in raw_archived) or
                len(set(raw_archived)) != len(raw_archived)):
            raise BatteryPackStoreFormatError("Invalid archived_pack_ids.")
        raw_owners = data.get("retained_history_owners", {})
        if not isinstance(raw_owners, dict):
            raise BatteryPackStoreFormatError("Invalid retained_history_owners.")
        for observation_id, owner in raw_owners.items():
            try:
                cls._validate_fingerprint(observation_id)
            except BatteryPackStoreError as exc:
                raise BatteryPackStoreFormatError(
                    "Invalid retained history observation ID."
                ) from exc
            if owner not in pack_ids:
                raise BatteryPackStoreFormatError(
                    "Retained history owner must be an existing Pack ID."
                )
        raw_filenames = data.get("log_filenames", {})
        if not isinstance(raw_filenames, dict):
            raise BatteryPackStoreFormatError("Invalid log_filenames.")
        log_filenames = {}
        for fingerprint, raw_names in raw_filenames.items():
            try:
                cls._validate_fingerprint(fingerprint)
            except BatteryPackStoreError as exc:
                raise BatteryPackStoreFormatError(
                    "Invalid filename fingerprint."
                ) from exc
            if not isinstance(raw_names, list) or not raw_names:
                raise BatteryPackStoreFormatError("Invalid log filename list.")
            for name in raw_names:
                try:
                    cls._validate_filename(name)
                except BatteryPackStoreError as exc:
                    raise BatteryPackStoreFormatError(str(exc)) from exc
            if len(set(raw_names)) != len(raw_names):
                raise BatteryPackStoreFormatError("Duplicate log filename.")
            log_filenames[fingerprint] = tuple(raw_names)
        raw_aliases = data.get("pack_aliases", {})
        if not isinstance(raw_aliases, dict):
            raise BatteryPackStoreFormatError("Invalid pack_aliases.")
        for historical, owner in raw_aliases.items():
            try:
                normalized = cls._normalize_pack_id(historical)
            except BatteryPackStoreError as exc:
                raise BatteryPackStoreFormatError(str(exc)) from exc
            if normalized != historical or historical in pack_ids or owner not in pack_ids:
                raise BatteryPackStoreFormatError("Invalid historical Pack ID alias.")
        return pack_ids, associations, raw_archived, raw_owners, log_filenames, raw_aliases

    @staticmethod
    def _validate_association(
        data: object,
        pack_ids: list[str],
    ) -> LogPackAssociation:
        if not isinstance(data, dict) or "state" not in data:
            raise BatteryPackStoreFormatError("Invalid log association.")
        if data["state"] == LogPackState.NOT_TRACKED.value:
            if set(data) != {"state"}:
                raise BatteryPackStoreFormatError("Invalid not-tracked association.")
            return LogPackAssociation(LogPackState.NOT_TRACKED)
        if data["state"] == LogPackState.TRACKED.value:
            if set(data) != {"state", "pack_id"} or data["pack_id"] not in pack_ids:
                raise BatteryPackStoreFormatError("Invalid tracked association.")
            return LogPackAssociation(LogPackState.TRACKED, data["pack_id"])
        raise BatteryPackStoreFormatError("Unknown log association state.")

    @staticmethod
    def _normalize_pack_id(pack_id: object) -> str:
        if not isinstance(pack_id, str) or not pack_id.strip():
            raise BatteryPackStoreError("Pack ID must be a non-empty string.")
        return pack_id.strip()

    @staticmethod
    def _validate_filename(name: object) -> None:
        if (not isinstance(name, str) or not name or name in (".", "..")
                or "/" in name or "\\" in name or "\x00" in name):
            raise BatteryPackStoreError("Log filename must be a basename.")

    @staticmethod
    def _validate_fingerprint(fingerprint: object) -> None:
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise BatteryPackStoreError("Invalid SHA-256 log fingerprint.")
