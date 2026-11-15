"""Explicit migration of repository-local APT persistent data."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .application_data import application_data_directory
from .battery_pack_history import BatteryPackHistoryStore
from .battery_pack_store import BatteryPackStore
from .range_walk_history import RangeWalkHistoryStore


_EVIDENCE_DIRECTORY = "range_walk_csv"


class DataMigrationError(ValueError):
    """Persistent data cannot be migrated safely."""


@dataclass(frozen=True)
class DataMigrationResult:
    """Validated migration plan and its publication state."""

    source: Path
    destination: Path
    relative_paths: tuple[Path, ...]
    applied: bool


def migrate_persistent_data(
    source_data_directory: str | Path,
    destination: str | Path | None = None,
    *,
    apply: bool = False,
) -> DataMigrationResult:
    """Validate and optionally migrate one explicit legacy ``Data`` directory.

    Dry-run is the default. Applying creates a same-filesystem staging directory,
    validates the copied data, and then renames it to the absent destination.
    """
    source = _validated_source_directory(source_data_directory)
    target = _destination_path(destination)
    _validate_separation(source, target)
    _require_absent_destination(target)
    relative_paths = _validate_managed_data(source)

    result = DataMigrationResult(source, target, relative_paths, applied=False)
    if not apply:
        return result

    source_identities = _file_identities(source, relative_paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            dir=target.parent,
            prefix=f".{target.name}.migration-",
        )
    )
    published = False
    try:
        _copy_managed_data(source, staging, relative_paths)
        current_source_identities = _file_identities(source, relative_paths)
        if current_source_identities != source_identities:
            raise DataMigrationError(
                "Source managed files changed during migration."
            )
        staged_identities = _file_identities(staging, relative_paths)
        if staged_identities != current_source_identities:
            changed = sorted(
                str(path)
                for path in relative_paths
                if staged_identities.get(path)
                != current_source_identities.get(path)
            )
            raise DataMigrationError(
                "Staged file identity differs from its source: "
                + ", ".join(changed)
            )
        staged_paths = _validate_managed_data(staging)
        if staged_paths != relative_paths:
            raise DataMigrationError("Staged data does not match the migration plan.")
        _require_absent_destination(target)
        staging.rename(target)
        published = True
    except DataMigrationError:
        raise
    except Exception as exc:
        raise DataMigrationError(f"Unable to migrate persistent data: {exc}") from exc
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)

    return DataMigrationResult(source, target, relative_paths, applied=True)


def _validated_source_directory(path: str | Path) -> Path:
    source = Path(path).expanduser()
    if source.is_symlink():
        raise DataMigrationError("Source Data directory must not be a symlink.")
    if not source.exists():
        raise DataMigrationError(f"Source Data directory does not exist: {source}")
    if not source.is_dir():
        raise DataMigrationError(f"Source Data path is not a directory: {source}")
    return source.resolve()


def _destination_path(path: str | Path | None) -> Path:
    target = application_data_directory() if path is None else Path(path).expanduser()
    return target.absolute()


def _validate_separation(source: Path, destination: Path) -> None:
    resolved_destination = destination.resolve(strict=False)
    if resolved_destination == source or source in resolved_destination.parents:
        raise DataMigrationError(
            "Destination must be outside the source Data directory."
        )


def _require_absent_destination(destination: Path) -> None:
    if os.path.lexists(destination):
        raise DataMigrationError(f"Destination already exists: {destination}")


def _validate_managed_data(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    validators = {
        "battery_packs.json": BatteryPackStore,
        "battery_pack_history.json": BatteryPackHistoryStore,
    }
    try:
        for filename, store_type in validators.items():
            path = root / filename
            if not _optional_regular_file(path):
                continue
            store_type(path)
            paths.append(Path(filename))

        history_path = root / "range_walk_history.json"
        evidence_dir = root / _EVIDENCE_DIRECTORY
        history_present = _optional_regular_file(history_path)
        evidence_present = _optional_directory(evidence_dir)

        expected_evidence: set[str] = set()
        if history_present:
            store = RangeWalkHistoryStore(history_path, evidence_dir)
            records, walks = store.validated_history()
            expected_evidence = {
                record.stored_csv_path.name for record in (*records, *walks)
            }
            paths.append(Path(history_path.name))

        actual_evidence: set[str] = set()
        if evidence_present:
            for entry in evidence_dir.iterdir():
                if entry.is_symlink() or not entry.is_file():
                    raise DataMigrationError(
                        f"Unsafe managed Range-Walk evidence entry: {entry}"
                    )
                actual_evidence.add(entry.name)

        if actual_evidence != expected_evidence:
            unexpected = sorted(actual_evidence - expected_evidence)
            missing = sorted(expected_evidence - actual_evidence)
            details = []
            if unexpected:
                details.append("unexpected: " + ", ".join(unexpected))
            if missing:
                details.append("missing: " + ", ".join(missing))
            raise DataMigrationError(
                "Range-Walk managed evidence is inconsistent ("
                + "; ".join(details)
                + ")."
            )
        paths.extend(
            Path(_EVIDENCE_DIRECTORY) / filename
            for filename in sorted(expected_evidence)
        )
    except DataMigrationError:
        raise
    except Exception as exc:
        raise DataMigrationError(f"Persistent data validation failed: {exc}") from exc

    if not paths:
        raise DataMigrationError("Source contains no supported persistent data.")
    return tuple(paths)


def _optional_regular_file(path: Path) -> bool:
    if path.is_symlink():
        raise DataMigrationError(f"Managed data file must not be a symlink: {path}")
    if not path.exists():
        return False
    if not path.is_file():
        raise DataMigrationError(f"Managed data path is not a file: {path}")
    return True


def _optional_directory(path: Path) -> bool:
    if path.is_symlink():
        raise DataMigrationError(
            f"Managed data directory must not be a symlink: {path}"
        )
    if not path.exists():
        return False
    if not path.is_dir():
        raise DataMigrationError(f"Managed evidence path is not a directory: {path}")
    return True


def _copy_managed_data(
    source: Path,
    staging: Path,
    relative_paths: tuple[Path, ...],
) -> None:
    for relative_path in relative_paths:
        source_path = source / relative_path
        target_path = staging / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _file_identities(
    root: Path,
    relative_paths: tuple[Path, ...],
) -> dict[Path, str]:
    identities = {}
    for relative_path in relative_paths:
        digest = hashlib.sha256()
        with (root / relative_path).open("rb") as managed_file:
            for chunk in iter(lambda: managed_file.read(1024 * 1024), b""):
                digest.update(chunk)
        identities[relative_path] = digest.hexdigest()
    return identities
