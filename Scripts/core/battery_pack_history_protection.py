"""Coordinated Pack History deletion with durable undo journal."""

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from .battery_pack_history import DEFAULT_HISTORY_PATH, BatteryPackHistoryStore
from .battery_pack_history_v2 import BatteryPackHistoryV2Store
from .battery_pack_store import BatteryPackStoreError

DEFAULT_V2_HISTORY_PATH = DEFAULT_HISTORY_PATH.with_name("battery_pack_history_v2.json")
WINDOWS_DIRECTORY_SYNC_UNAVAILABLE = os.name == "nt"


class DeletionOutcomeUncertain(BatteryPackStoreError):
    """A committed marker is visible, but its durability could not be confirmed."""


def revision(path):
    """Content revision, including a distinct initially absent state."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return "missing"


def _directory_sync(path):
    if WINDOWS_DIRECTORY_SYNC_UNAVAILABLE:
        # Windows cannot fsync a directory through os.open. File contents are
        # fsynced separately; process-interruption recovery remains available.
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _distinct(paths):
    if any(Path(path).is_symlink() for path in paths):
        raise BatteryPackStoreError("Pack and history store paths cannot be symbolic links.")
    resolved = [Path(path).resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise BatteryPackStoreError("Pack and history store paths must be distinct.")
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            if Path(left).exists() and Path(right).exists() and os.path.samefile(left, right):
                raise BatteryPackStoreError("Pack and history store paths overlap.")


def journal_path(pack_path):
    return Path(pack_path).with_name(f".{Path(pack_path).name}.delete-journal")


def _validated_manifest(journal, paths):
    manifest = json.loads((journal / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Deletion journal manifest must be an object.")
    revisions = manifest.get("revisions")
    if (set(manifest) != {"version", "paths", "revisions", "state", "checksum"}
            or type(manifest.get("version")) is not int or manifest["version"] != 1
            or manifest.get("paths") != [str(path.resolve()) for path in paths]
            or manifest.get("state") not in ("prepared", "committed")
            or not isinstance(revisions, list) or len(revisions) != 3
            or any(not isinstance(item, str) or (item != "missing" and
                   (len(item) != 64 or any(char not in "0123456789abcdef" for char in item)))
                   for item in revisions)
            or manifest.get("checksum") != _manifest_checksum(manifest)):
        raise ValueError("Invalid deletion journal manifest.")
    return manifest


def _manifest_checksum(manifest):
    fields = {key: value for key, value in manifest.items() if key != "checksum"}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _dispose_journal(journal):
    """Atomically retire the active journal before best-effort file cleanup."""
    retired = journal.with_name(f"{journal.name}.completed-{uuid.uuid4().hex}")
    os.replace(journal, retired)
    _directory_sync(journal.parent)
    try:
        shutil.rmtree(retired)
    except OSError:
        # Retired journals never represent an active transaction. The complete
        # manifest and backups remain available for forensic inspection.
        pass


def recover_pending_deletion(pack_path, v1_path, v2_path, *, cleanup=True):
    """Restore a prepared transaction, or finish cleanup of a committed one."""
    paths = tuple(Path(path) for path in (pack_path, v1_path, v2_path))
    _distinct(paths)
    journal = journal_path(pack_path)
    if not journal.exists():
        return False
    try:
        manifest = _validated_manifest(journal, paths)
        if manifest["state"] == "prepared":
            for index, path in enumerate(paths):
                expected = manifest["revisions"][index]
                backup = journal / f"{index}.backup"
                if expected == "missing":
                    if backup.exists():
                        raise ValueError("Unexpected deletion backup.")
                elif revision(backup) != expected:
                    raise ValueError("Deletion backup does not match its revision.")
            for index, path in enumerate(paths):
                expected = manifest["revisions"][index]
                if expected == "missing":
                    path.unlink(missing_ok=True)
                elif revision(path) != expected:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                        temporary = Path(output.name)
                        output.write((journal / f"{index}.backup").read_bytes())
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, path)
                _directory_sync(path.parent)
        if cleanup:
            _dispose_journal(journal)
        return True
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise BatteryPackStoreError(
            f"Pack deletion recovery failed; recovery material retained at {journal}: {exc}"
        ) from exc


class CoordinatedHistory:
    """Explicit-path v1 and v2 stores for management, never for ingestion."""

    def __init__(self, pack_path, v1_path=DEFAULT_HISTORY_PATH,
                 v2_path=DEFAULT_V2_HISTORY_PATH,
                 v1_factory=BatteryPackHistoryStore,
                 v2_factory=BatteryPackHistoryV2Store):
        self.pack_path = Path(pack_path)
        self.v1_path = Path(v1_path)
        self.v2_path = Path(v2_path)
        recover_pending_deletion(self.pack_path, self.v1_path, self.v2_path)
        self.v1 = v1_factory(self.v1_path)
        self.v2 = v2_factory(self.v2_path)
        self.revisions = (revision(self.v1_path), revision(self.v2_path))

    @property
    def observations(self):
        return (*self.v1.observations, *self.v2.observations)


def _prepare_journal(paths):
    journal = journal_path(paths[0])
    revisions = [revision(path) for path in paths]
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.mkdir()
    try:
        for index, path in enumerate(paths):
            if revisions[index] != "missing":
                with (journal / f"{index}.backup").open("wb") as backup:
                    backup.write(path.read_bytes())
                    backup.flush()
                    os.fsync(backup.fileno())
                if revision(journal / f"{index}.backup") != revisions[index]:
                    raise BatteryPackStoreError("Store changed while preparing deletion backup.")
        manifest = {"version": 1, "paths": [str(path.resolve()) for path in paths],
                    "revisions": revisions, "state": "prepared"}
        _write_manifest(journal, manifest)
        _directory_sync(journal)
        _directory_sync(journal.parent)
    except Exception:
        shutil.rmtree(journal)
        raise
    return journal, manifest


def _write_manifest(journal, manifest):
    payload = dict(manifest)
    payload["checksum"] = _manifest_checksum(payload)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=journal,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, journal / "manifest.json")
    _directory_sync(journal)


def delete_coordinated(store, history, pack_id, expected_plan):
    """Delete three files under a recoverable undo journal."""
    paths = (store.path, history.v1.path, history.v2.path)
    _distinct(paths)
    if journal_path(store.path).exists():
        raise BatteryPackStoreError("Pending deletion recovery must complete first.")
    plan = store.deletion_plan(pack_id, history)
    if expected_plan is not None and plan != expected_plan:
        raise BatteryPackStoreError("Pack associations or history changed after confirmation.")
    if plan.store_revisions != tuple(revision(path) for path in paths):
        raise BatteryPackStoreError("Pack or history changed after deletion planning.")
    associations = dict(store._associations)
    from .battery_pack_store import LogPackAssociation, LogPackState
    for fingerprint in plan.log_fingerprints:
        associations[fingerprint] = LogPackAssociation(LogPackState.NOT_TRACKED)
    owners = {key: owner for key, owner in store._history_owners.items()
              if key not in (*plan.observation_ids, *plan.v2_observation_ids)}
    owners.update(plan.retained_history_owners)
    aliases = {key: owner for key, owner in store._pack_aliases.items() if owner != plan.pack_id}
    v1_remaining = {row.observation_id: row for row in history.v1.observations
                    if row.observation_id not in plan.observation_ids}
    v2_remaining = {row.observation_id: row for row in history.v2.observations
                    if row.observation_id not in plan.v2_observation_ids}
    journal, manifest = _prepare_journal(paths)
    try:
        if plan.observation_ids:
            history.v1._save(v1_remaining)
            _directory_sync(history.v1.path.parent)
        if plan.v2_observation_ids:
            history.v2._save(v2_remaining)
            _directory_sync(history.v2.path.parent)
        store._save([pack for pack in store._pack_ids if pack != plan.pack_id],
                    associations, [pack for pack in store._archived_pack_ids if pack != plan.pack_id],
                    owners, pack_aliases=aliases)
        _directory_sync(store.path.parent)
        manifest["state"] = "committed"
        _write_manifest(journal, manifest)
    except Exception as write_error:
        try:
            state = _validated_manifest(journal, paths)["state"]
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise DeletionOutcomeUncertain(
                f"Deletion outcome uncertain: journal state cannot be verified at {journal}."
            ) from exc
        if state == "committed":
            raise DeletionOutcomeUncertain(
                f"Deletion outcome uncertain: committed marker is visible at {journal}; "
                "refresh Pack Management before retrying."
            ) from write_error
        recover_pending_deletion(*paths, cleanup=False)
        try:
            for target in (store, history.v1, history.v2):
                target.__dict__.update(type(target)(target.path).__dict__)
        except Exception as exc:
            raise BatteryPackStoreError(
                f"Deletion rollback could not reload memory; recovery retained at {journal}."
            ) from exc
        _dispose_journal(journal)
        raise
    try:
        _dispose_journal(journal)
    except OSError:
        # All stores and the committed marker are durable. A failed retirement
        # leaves the active journal for the next management entry to clean up.
        pass
    return plan
