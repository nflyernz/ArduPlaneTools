"""Persistent physical battery Pack IDs and source-log associations."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .application_data import application_data_directory

SCHEMA_VERSION = 1
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
        self._associations: dict[str, LogPackAssociation] = {}
        self._load()

    @property
    def pack_ids(self) -> tuple[str, ...]:
        """Return known physical Pack IDs in creation order."""
        return tuple(self._pack_ids)

    def association_for(self, fingerprint: str) -> LogPackAssociation:
        """Return the stored decision, or explicit unseen state."""
        self._validate_fingerprint(fingerprint)
        return self._associations.get(
            fingerprint,
            LogPackAssociation(LogPackState.UNSEEN),
        )

    def associate(self, fingerprint: str, pack_id: str) -> None:
        """Associate a source log with an existing Pack ID."""
        self._validate_fingerprint(fingerprint)
        normalized_id = self._normalize_pack_id(pack_id)
        if normalized_id not in self._pack_ids:
            raise BatteryPackStoreError(f"Unknown Pack ID: {normalized_id}")
        associations = dict(self._associations)
        associations[fingerprint] = LogPackAssociation(
            LogPackState.TRACKED,
            normalized_id,
        )
        self._save(self._pack_ids, associations)

    def create_and_associate(self, fingerprint: str, pack_id: str) -> None:
        """Create one Pack ID and associate the source log atomically."""
        self._validate_fingerprint(fingerprint)
        normalized_id = self._normalize_pack_id(pack_id)
        if normalized_id in self._pack_ids:
            raise BatteryPackStoreError(f"Pack ID already exists: {normalized_id}")
        pack_ids = [*self._pack_ids, normalized_id]
        associations = dict(self._associations)
        associations[fingerprint] = LogPackAssociation(
            LogPackState.TRACKED,
            normalized_id,
        )
        self._save(pack_ids, associations)

    def mark_not_tracked(self, fingerprint: str) -> None:
        """Persist an explicit decision not to track this source log."""
        self._validate_fingerprint(fingerprint)
        associations = dict(self._associations)
        associations[fingerprint] = LogPackAssociation(LogPackState.NOT_TRACKED)
        self._save(self._pack_ids, associations)

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

        self._save(pack_ids, associations)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BatteryPackStoreFormatError(
                f"Unable to read {self.path}: {exc}"
            ) from exc
        self._pack_ids, self._associations = self._validate_data(data)

    def _save(
        self,
        pack_ids: list[str],
        associations: dict[str, LogPackAssociation],
    ) -> None:
        data = {
            "version": SCHEMA_VERSION,
            "pack_ids": pack_ids,
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

    @classmethod
    def _validate_data(
        cls,
        data: object,
    ) -> tuple[list[str], dict[str, LogPackAssociation]]:
        if not isinstance(data, dict):
            raise BatteryPackStoreFormatError("Battery-pack store must be an object.")
        if set(data) != {"version", "pack_ids", "log_associations"}:
            raise BatteryPackStoreFormatError(
                "Battery-pack store contains unexpected or missing fields."
            )
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise BatteryPackStoreFormatError(
                "Battery-pack version must be an integer."
            )
        if version != SCHEMA_VERSION:
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
        return pack_ids, associations

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
    def _validate_fingerprint(fingerprint: object) -> None:
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise BatteryPackStoreError("Invalid SHA-256 log fingerprint.")
