"""Versioned durable storage for Range-Walk baselines and later walks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .range_walk import LandmarkMarker, WalkSettings, select_landmarks


HISTORY_SCHEMA_VERSION = 2
BASELINE_SCHEMA_VERSION = 1
ADDITIONAL_WALK_SCHEMA_VERSION = 1
EVIDENCE_SEMANTICS_VERSION = "range-walk-gui-auto-33pct-neutral-v1"
DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[2] / "Data" / "range_walk_history.json"
)
DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2] / "Data" / "range_walk_csv"
)


class RangeWalkHistoryError(ValueError):
    """Base error for Range-Walk history and evidence operations."""


class RangeWalkHistoryFormatError(RangeWalkHistoryError):
    """Stored Range-Walk history does not match the supported schema."""


class DuplicateRangeWalkEvidenceError(RangeWalkHistoryError):
    """The same source CSV is already owned by a saved Range-Walk record."""


@dataclass(frozen=True)
class StoredWalk1Baseline:
    """One durable Walk 1 baseline with preserved source evidence."""

    baseline_id: str
    created_at_utc: str
    original_csv_filename: str
    original_csv_path: str
    csv_sha256: str
    stored_csv_path: Path
    label: str
    antenna: str
    landmark_names: tuple[str, ...]
    turnaround: str
    settings: WalkSettings
    candidates: tuple[LandmarkMarker, ...]
    candidate_numbers: tuple[int, ...]
    landmarks: tuple[LandmarkMarker, ...]
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime


@dataclass(frozen=True)
class StoredAdditionalWalk:
    """One later walk associated with an immutable Walk 1 baseline."""

    walk_id: str
    parent_baseline_id: str
    created_at_utc: str
    original_csv_filename: str
    original_csv_path: str
    csv_sha256: str
    stored_csv_path: Path
    label: str
    antenna: str
    settings: WalkSettings
    candidates: tuple[LandmarkMarker, ...]
    candidate_numbers: tuple[int | None, ...]
    landmarks: tuple[LandmarkMarker | None, ...]
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime

    @property
    def confirmed_landmark_count(self) -> int:
        return sum(marker is not None for marker in self.landmarks)

    @property
    def complete_section_count(self) -> int:
        return sum(
            first is not None
            and second is not None
            and first.release < second.onset
            for first, second in zip(self.landmarks, self.landmarks[1:])
        )


def fingerprint_csv(path: str | Path) -> str:
    """Return the SHA-256 identity of one CSV file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RangeWalkHistoryStore:
    """Strict atomic persistence for baselines and their associated walks."""

    def __init__(
        self,
        path: str | Path = DEFAULT_HISTORY_PATH,
        evidence_dir: str | Path | None = None,
    ):
        self.path = Path(path)
        self.evidence_dir = Path(evidence_dir or DEFAULT_EVIDENCE_DIR)
        self._records: dict[str, StoredWalk1Baseline] = {}
        self._walks: dict[str, StoredAdditionalWalk] = {}
        self._load()

    @property
    def records(self) -> tuple[StoredWalk1Baseline, ...]:
        """Return baselines in creation order, then stable ID order."""
        return tuple(
            sorted(
                self._records.values(),
                key=lambda record: (record.created_at_utc, record.baseline_id),
            )
        )

    def validated_records(self) -> tuple[StoredWalk1Baseline, ...]:
        """Return records only after validating every managed CSV identity."""
        for record in self.records:
            self._validate_managed_evidence(record, record.baseline_id)
        return self.records

    @property
    def walks(self) -> tuple[StoredAdditionalWalk, ...]:
        """Return later walks in creation order, then stable ID order."""
        return tuple(
            sorted(
                self._walks.values(),
                key=lambda record: (record.created_at_utc, record.walk_id),
            )
        )

    def validated_walks(self) -> tuple[StoredAdditionalWalk, ...]:
        """Return later walks after validating their managed CSV evidence."""
        for record in self.walks:
            self._validate_managed_evidence(record, record.walk_id)
        return self.walks

    def validated_history(
        self,
    ) -> tuple[tuple[StoredWalk1Baseline, ...], tuple[StoredAdditionalWalk, ...]]:
        """Validate and return every baseline and associated later walk."""
        return self.validated_records(), self.validated_walks()

    def add_baseline(self, baseline) -> StoredWalk1Baseline:
        """Atomically preserve a source CSV and append one unique baseline."""
        source = Path(baseline.source_path).expanduser().resolve()
        if not source.is_file():
            raise RangeWalkHistoryError(f"Source CSV is unavailable: {source}")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        temporary_path, source_sha256 = self._copy_and_hash(source)
        target = self.evidence_dir / f"{source_sha256}.csv"
        created_evidence = False
        try:
            if source_sha256 != baseline.source_sha256:
                raise RangeWalkHistoryError(
                    "Source CSV changed since marker detection; detect markers again."
                )
            duplicate = self._record_with_fingerprint(source_sha256)
            if duplicate is not None:
                raise DuplicateRangeWalkEvidenceError(
                    "CSV evidence is already saved by record "
                    f"{_record_id(duplicate)}."
                )
            if target.exists():
                if not target.is_file() or fingerprint_csv(target) != source_sha256:
                    raise RangeWalkHistoryError(
                        f"Managed CSV conflicts with its checksum name: {target}"
                    )
                temporary_path.unlink()
            else:
                os.replace(temporary_path, target)
                created_evidence = True

            record = self._new_record(baseline, source, source_sha256, target)
            candidate = dict(self._records)
            candidate[record.baseline_id] = record
            self._save(candidate)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            if created_evidence and target.exists():
                target.unlink()
            raise
        return record

    def add_additional_walk(self, walk) -> StoredAdditionalWalk:
        """Atomically preserve and associate one later walk with its baseline."""
        parent = self._records.get(walk.parent_baseline_id)
        if parent is None:
            raise RangeWalkHistoryError(
                f"Unknown parent Walk 1 baseline: {walk.parent_baseline_id}"
            )
        if walk.settings != parent.settings:
            raise RangeWalkHistoryError(
                "Additional-walk RF settings must be inherited from its baseline."
            )
        source = Path(walk.source_path).expanduser().resolve()
        if not source.is_file():
            raise RangeWalkHistoryError(f"Source CSV is unavailable: {source}")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        temporary_path, source_sha256 = self._copy_and_hash(source)
        target = self.evidence_dir / f"{source_sha256}.csv"
        created_evidence = False
        try:
            if source_sha256 != walk.source_sha256:
                raise RangeWalkHistoryError(
                    "Source CSV changed since marker detection; detect markers again."
                )
            duplicate = self._record_with_fingerprint(source_sha256)
            if duplicate is not None:
                raise DuplicateRangeWalkEvidenceError(
                    "CSV evidence is already saved by record "
                    f"{_record_id(duplicate)}."
                )
            if target.exists():
                if not target.is_file() or fingerprint_csv(target) != source_sha256:
                    raise RangeWalkHistoryError(
                        f"Managed CSV conflicts with its checksum name: {target}"
                    )
                temporary_path.unlink()
            else:
                os.replace(temporary_path, target)
                created_evidence = True
            record = self._new_additional_walk(
                walk, source, source_sha256, target
            )
            candidate = dict(self._walks)
            candidate[record.walk_id] = record
            self._save(self._records, candidate)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            if created_evidence and target.exists():
                target.unlink()
            raise
        return record

    def _record_with_fingerprint(self, source_sha256: str):
        return next(
            (
                record
                for record in (*self._records.values(), *self._walks.values())
                if record.csv_sha256 == source_sha256
            ),
            None,
        )

    def update_baseline_metadata(
        self,
        baseline_id: str,
        expected_record: StoredWalk1Baseline,
        baseline,
    ) -> StoredWalk1Baseline:
        """Atomically update only operator-entered metadata for one baseline."""
        current = self._records.get(baseline_id)
        if current is None:
            raise RangeWalkHistoryError(f"Unknown Walk 1 baseline: {baseline_id}")
        if current != expected_record:
            raise RangeWalkHistoryError(
                "Saved Walk 1 changed since it was loaded; refresh before updating."
            )
        self._validate_managed_evidence(current, current.baseline_id)
        self._require_unchanged_evidence(current, baseline)
        updated = replace(
            current,
            label=baseline.label,
            antenna=baseline.antenna,
            settings=baseline.settings,
        )
        updated = self._record_from_dict(self._record_to_dict(updated))
        candidate = dict(self._records)
        candidate[baseline_id] = updated
        updated_walks = {
            walk_id: replace(walk, settings=updated.settings)
            if walk.parent_baseline_id == baseline_id
            else walk
            for walk_id, walk in self._walks.items()
        }
        if self._walks:
            self._save(candidate, updated_walks)
        else:
            self._save(candidate)
        return updated

    @staticmethod
    def _require_unchanged_evidence(current: StoredWalk1Baseline, baseline) -> None:
        immutable = (
            (baseline.source_sha256, current.csv_sha256),
            (baseline.landmark_names, current.landmark_names),
            (baseline.turnaround, current.turnaround),
            (baseline.candidates, current.candidates),
            (baseline.candidate_numbers, current.candidate_numbers),
            (baseline.landmarks, current.landmarks),
            (baseline.direction_used, current.direction_used),
            (baseline.direction_assessment, current.direction_assessment),
            (baseline.recording_start, current.recording_start),
            (baseline.recording_end, current.recording_end),
        )
        if any(proposed != stored for proposed, stored in immutable):
            raise RangeWalkHistoryError(
                "Saved marker evidence and landmark mapping cannot be changed by "
                "a metadata update."
            )

    def _copy_and_hash(self, source: Path) -> tuple[Path, str]:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.evidence_dir,
            prefix=".range-walk-csv.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        try:
            with source.open("rb") as source_file, os.fdopen(
                descriptor, "wb"
            ) as target_file:
                for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                    digest.update(chunk)
                    target_file.write(chunk)
                target_file.flush()
                os.fsync(target_file.fileno())
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        return temporary_path, digest.hexdigest()

    def _new_record(
        self,
        baseline,
        source: Path,
        source_sha256: str,
        target: Path,
    ) -> StoredWalk1Baseline:
        record = StoredWalk1Baseline(
            baseline_id=uuid4().hex,
            created_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            original_csv_filename=source.name,
            original_csv_path=str(source),
            csv_sha256=source_sha256,
            stored_csv_path=target.resolve(),
            label=baseline.label,
            antenna=baseline.antenna,
            landmark_names=baseline.landmark_names,
            turnaround=baseline.turnaround,
            settings=baseline.settings,
            candidates=baseline.candidates,
            candidate_numbers=baseline.candidate_numbers,
            landmarks=baseline.landmarks,
            direction_used=baseline.direction_used,
            direction_assessment=baseline.direction_assessment,
            recording_start=baseline.recording_start,
            recording_end=baseline.recording_end,
        )
        return self._record_from_dict(self._record_to_dict(record))

    def _new_additional_walk(
        self,
        walk,
        source: Path,
        source_sha256: str,
        target: Path,
    ) -> StoredAdditionalWalk:
        record = StoredAdditionalWalk(
            walk_id=uuid4().hex,
            parent_baseline_id=walk.parent_baseline_id,
            created_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            original_csv_filename=source.name,
            original_csv_path=str(source),
            csv_sha256=source_sha256,
            stored_csv_path=target.resolve(),
            label=walk.label,
            antenna=walk.antenna,
            settings=walk.settings,
            candidates=walk.candidates,
            candidate_numbers=walk.candidate_numbers,
            landmarks=walk.landmarks,
            direction_used=walk.direction_used,
            direction_assessment=walk.direction_assessment,
            recording_start=walk.recording_start,
            recording_end=walk.recording_end,
        )
        return self._walk_from_dict(self._walk_to_dict(record))

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RangeWalkHistoryFormatError(
                f"Unable to read {self.path}: {exc}"
            ) from exc
        if not isinstance(data, dict) or set(data) not in (
            {"version", "baselines"},
            {"version", "baselines", "walks"},
        ):
            raise RangeWalkHistoryFormatError(
                "Range-Walk history contains unexpected or missing fields."
            )
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise RangeWalkHistoryFormatError(
                "Range-Walk history version must be an integer."
            )
        if version not in {1, HISTORY_SCHEMA_VERSION}:
            raise RangeWalkHistoryFormatError(
                f"Unsupported Range-Walk history version: {version}"
            )
        if version == 1 and set(data) != {"version", "baselines"}:
            raise RangeWalkHistoryFormatError("Invalid version-1 Range-Walk history.")
        if version == HISTORY_SCHEMA_VERSION and set(data) != {
            "version",
            "baselines",
            "walks",
        }:
            raise RangeWalkHistoryFormatError("Invalid version-2 Range-Walk history.")
        raw_records = data["baselines"]
        if not isinstance(raw_records, dict):
            raise RangeWalkHistoryFormatError("baselines must be an object.")
        records = {}
        fingerprints = set()
        for baseline_id, raw_record in raw_records.items():
            record = self._record_from_dict(raw_record)
            if baseline_id != record.baseline_id:
                raise RangeWalkHistoryFormatError(
                    "Baseline map key does not match baseline ID."
                )
            if baseline_id in records or record.csv_sha256 in fingerprints:
                raise RangeWalkHistoryFormatError(
                    "Range-Walk history contains duplicate baseline evidence."
                )
            records[baseline_id] = record
            fingerprints.add(record.csv_sha256)
        self._records = records
        raw_walks = data.get("walks", {})
        if not isinstance(raw_walks, dict):
            raise RangeWalkHistoryFormatError("walks must be an object.")
        walks = {}
        for walk_id, raw_walk in raw_walks.items():
            record = self._walk_from_dict(raw_walk)
            if walk_id != record.walk_id:
                raise RangeWalkHistoryFormatError(
                    "Walk map key does not match walk ID."
                )
            if walk_id in records or walk_id in walks:
                raise RangeWalkHistoryFormatError("Duplicate Range-Walk record ID.")
            if record.parent_baseline_id not in records:
                raise RangeWalkHistoryFormatError(
                    f"Unknown parent baseline for walk {walk_id}."
                )
            if record.settings != records[record.parent_baseline_id].settings:
                raise RangeWalkHistoryFormatError(
                    f"Walk {walk_id} settings do not match its parent baseline."
                )
            if record.csv_sha256 in fingerprints:
                raise RangeWalkHistoryFormatError(
                    "Range-Walk history contains duplicate CSV evidence."
                )
            walks[walk_id] = record
            fingerprints.add(record.csv_sha256)
        self._walks = walks

    def _save(
        self,
        records: dict[str, StoredWalk1Baseline],
        walks: dict[str, StoredAdditionalWalk] | None = None,
    ) -> None:
        saved_walks = self._walks if walks is None else walks
        data = {
            "version": HISTORY_SCHEMA_VERSION,
            "baselines": {
                key: self._record_to_dict(records[key]) for key in sorted(records)
            },
            "walks": {
                key: self._walk_to_dict(saved_walks[key]) for key in sorted(saved_walks)
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
            with os.fdopen(descriptor, "w", encoding="utf-8") as history_file:
                json.dump(data, history_file, indent=2, sort_keys=True, allow_nan=False)
                history_file.write("\n")
                history_file.flush()
                os.fsync(history_file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        self._records = records
        self._walks = saved_walks

    def _validate_managed_evidence(self, record, record_id: str) -> None:
        expected = self.evidence_dir / f"{record.csv_sha256}.csv"
        if record.stored_csv_path != expected.resolve():
            raise RangeWalkHistoryFormatError(
                f"Managed CSV path is inconsistent for record {record_id}."
            )
        if not expected.is_file():
            raise RangeWalkHistoryError(
                f"Managed CSV is missing for record {record_id}: {expected}"
            )
        if fingerprint_csv(expected) != record.csv_sha256:
            raise RangeWalkHistoryError(
                f"Managed CSV checksum mismatch for record {record_id}."
            )

    def _record_to_dict(self, record: StoredWalk1Baseline) -> dict[str, object]:
        return {
            "baseline_schema_version": BASELINE_SCHEMA_VERSION,
            "record_type": "walk1_baseline",
            "evidence_semantics_version": EVIDENCE_SEMANTICS_VERSION,
            "baseline_id": record.baseline_id,
            "created_at_utc": record.created_at_utc,
            "original_csv_filename": record.original_csv_filename,
            "original_csv_path": record.original_csv_path,
            "csv_sha256": record.csv_sha256,
            "stored_csv_filename": record.stored_csv_path.name,
            "label": record.label,
            "antenna": record.antenna,
            "landmark_names": list(record.landmark_names),
            "turnaround": record.turnaround,
            "settings": {
                "tx_power": record.settings.tx_power,
                "packet_rate": record.settings.packet_rate,
                "rf_mode": record.settings.rf_mode,
                "dynamic_power": record.settings.dynamic_power,
            },
            "candidates": [_marker_to_dict(marker) for marker in record.candidates],
            "candidate_numbers": list(record.candidate_numbers),
            "confirmed_markers": [
                _marker_to_dict(marker) for marker in record.landmarks
            ],
            "direction_used": record.direction_used,
            "direction_assessment": record.direction_assessment,
            "recording_start": record.recording_start.isoformat(),
            "recording_end": record.recording_end.isoformat(),
        }

    def _walk_to_dict(self, record: StoredAdditionalWalk) -> dict[str, object]:
        return {
            "walk_schema_version": ADDITIONAL_WALK_SCHEMA_VERSION,
            "record_type": "additional_walk",
            "evidence_semantics_version": EVIDENCE_SEMANTICS_VERSION,
            "walk_id": record.walk_id,
            "parent_baseline_id": record.parent_baseline_id,
            "created_at_utc": record.created_at_utc,
            "original_csv_filename": record.original_csv_filename,
            "original_csv_path": record.original_csv_path,
            "csv_sha256": record.csv_sha256,
            "stored_csv_filename": record.stored_csv_path.name,
            "label": record.label,
            "antenna": record.antenna,
            "settings": {
                "tx_power": record.settings.tx_power,
                "packet_rate": record.settings.packet_rate,
                "rf_mode": record.settings.rf_mode,
                "dynamic_power": record.settings.dynamic_power,
            },
            "candidates": [_marker_to_dict(marker) for marker in record.candidates],
            "candidate_numbers": list(record.candidate_numbers),
            "confirmed_markers": [
                _marker_to_dict(marker) if marker is not None else None
                for marker in record.landmarks
            ],
            "direction_used": record.direction_used,
            "direction_assessment": record.direction_assessment,
            "recording_start": record.recording_start.isoformat(),
            "recording_end": record.recording_end.isoformat(),
        }

    def _walk_from_dict(self, data: object) -> StoredAdditionalWalk:
        fields = {
            "walk_schema_version",
            "record_type",
            "evidence_semantics_version",
            "walk_id",
            "parent_baseline_id",
            "created_at_utc",
            "original_csv_filename",
            "original_csv_path",
            "csv_sha256",
            "stored_csv_filename",
            "label",
            "antenna",
            "settings",
            "candidates",
            "candidate_numbers",
            "confirmed_markers",
            "direction_used",
            "direction_assessment",
            "recording_start",
            "recording_end",
        }
        if not isinstance(data, dict) or set(data) != fields:
            raise RangeWalkHistoryFormatError(
                "Additional walk contains unexpected or missing fields."
            )
        if (
            isinstance(data["walk_schema_version"], bool)
            or not isinstance(data["walk_schema_version"], int)
            or data["walk_schema_version"] != ADDITIONAL_WALK_SCHEMA_VERSION
        ):
            raise RangeWalkHistoryFormatError(
                f"Unsupported additional-walk schema: {data['walk_schema_version']}"
            )
        if data["record_type"] != "additional_walk":
            raise RangeWalkHistoryFormatError("Unsupported Range-Walk record type.")
        if data["evidence_semantics_version"] != EVIDENCE_SEMANTICS_VERSION:
            raise RangeWalkHistoryFormatError(
                "Unsupported Range-Walk evidence semantics: "
                f"{data['evidence_semantics_version']}"
            )
        walk_id = _record_identifier(data["walk_id"], "walk_id")
        parent_id = _record_identifier(
            data["parent_baseline_id"], "parent_baseline_id"
        )
        created_at = _datetime(data["created_at_utc"], "created_at_utc")
        if created_at.tzinfo is None or created_at.utcoffset().total_seconds() != 0:
            raise RangeWalkHistoryFormatError("created_at_utc must use UTC.")
        source_sha256 = _sha256(data["csv_sha256"])
        stored_filename = _filename(data["stored_csv_filename"])
        if stored_filename != f"{source_sha256}.csv":
            raise RangeWalkHistoryFormatError(
                "Managed CSV filename does not match its checksum."
            )
        settings = _settings(data["settings"])
        candidates = _marker_tuple(data["candidates"], "candidates")
        numbers = _optional_integer_tuple(
            data["candidate_numbers"], "candidate_numbers", 5
        )
        try:
            selected = select_landmarks(candidates, numbers, baseline=False)
        except ValueError as exc:
            raise RangeWalkHistoryFormatError(str(exc)) from exc
        confirmed = _optional_marker_tuple(
            data["confirmed_markers"], "confirmed_markers", 5
        )
        if confirmed != selected:
            raise RangeWalkHistoryFormatError(
                "Confirmed markers do not match the saved candidate mapping."
            )
        direction = _nonempty_string(data["direction_used"], "direction_used")
        if direction not in {"higher", "lower"}:
            raise RangeWalkHistoryFormatError("Invalid detection direction.")
        recording_start = _datetime(data["recording_start"], "recording_start")
        recording_end = _datetime(data["recording_end"], "recording_end")
        if recording_end < recording_start:
            raise RangeWalkHistoryFormatError("Invalid recording time span.")
        return StoredAdditionalWalk(
            walk_id,
            parent_id,
            data["created_at_utc"],
            _filename(data["original_csv_filename"]),
            _nonempty_string(data["original_csv_path"], "original_csv_path"),
            source_sha256,
            (self.evidence_dir / stored_filename).resolve(),
            _nonempty_string(data["label"], "label"),
            _nonempty_string(data["antenna"], "antenna"),
            settings,
            candidates,
            numbers,
            confirmed,
            direction,
            _nonempty_string(data["direction_assessment"], "direction_assessment"),
            recording_start,
            recording_end,
        )

    def _record_from_dict(self, data: object) -> StoredWalk1Baseline:
        fields = {
            "baseline_schema_version",
            "record_type",
            "evidence_semantics_version",
            "baseline_id",
            "created_at_utc",
            "original_csv_filename",
            "original_csv_path",
            "csv_sha256",
            "stored_csv_filename",
            "label",
            "antenna",
            "landmark_names",
            "turnaround",
            "settings",
            "candidates",
            "candidate_numbers",
            "confirmed_markers",
            "direction_used",
            "direction_assessment",
            "recording_start",
            "recording_end",
        }
        if not isinstance(data, dict) or set(data) != fields:
            raise RangeWalkHistoryFormatError(
                "Baseline contains unexpected or missing fields."
            )
        if (
            isinstance(data["baseline_schema_version"], bool)
            or not isinstance(data["baseline_schema_version"], int)
            or data["baseline_schema_version"] != BASELINE_SCHEMA_VERSION
        ):
            raise RangeWalkHistoryFormatError(
                "Unsupported Range-Walk baseline schema version: "
                f"{data['baseline_schema_version']}"
            )
        if data["record_type"] != "walk1_baseline":
            raise RangeWalkHistoryFormatError("Unsupported Range-Walk record type.")
        if data["evidence_semantics_version"] != EVIDENCE_SEMANTICS_VERSION:
            raise RangeWalkHistoryFormatError(
                "Unsupported Range-Walk evidence semantics: "
                f"{data['evidence_semantics_version']}"
            )
        baseline_id = _nonempty_string(data["baseline_id"], "baseline_id")
        if len(baseline_id) != 32 or any(
            character not in "0123456789abcdef" for character in baseline_id
        ):
            raise RangeWalkHistoryFormatError("Invalid baseline_id.")
        created_at = _datetime(data["created_at_utc"], "created_at_utc")
        if created_at.tzinfo is None or created_at.utcoffset().total_seconds() != 0:
            raise RangeWalkHistoryFormatError("created_at_utc must use UTC.")
        source_sha256 = _sha256(data["csv_sha256"])
        source_filename = _filename(data["original_csv_filename"])
        original_path = _nonempty_string(
            data["original_csv_path"], "original_csv_path"
        )
        stored_filename = _filename(data["stored_csv_filename"])
        if stored_filename != f"{source_sha256}.csv":
            raise RangeWalkHistoryFormatError(
                "Managed CSV filename does not match its checksum."
            )
        landmark_names = _string_tuple(data["landmark_names"], "landmark_names", 5)
        turnaround = _nonempty_string(data["turnaround"], "turnaround")
        if turnaround != landmark_names[4]:
            raise RangeWalkHistoryFormatError(
                "Turnaround must match the fifth landmark name."
            )
        settings_data = data["settings"]
        setting_fields = {"tx_power", "packet_rate", "rf_mode", "dynamic_power"}
        if not isinstance(settings_data, dict) or set(settings_data) != setting_fields:
            raise RangeWalkHistoryFormatError("Invalid RF settings.")
        settings = WalkSettings(
            *(
                _optional_normalized_string(settings_data[field], field)
                for field in ("tx_power", "packet_rate", "rf_mode", "dynamic_power")
            )
        )
        candidates = _marker_tuple(data["candidates"], "candidates")
        numbers = _integer_tuple(data["candidate_numbers"], "candidate_numbers", 5)
        try:
            selected = select_landmarks(candidates, numbers, baseline=True)
        except ValueError as exc:
            raise RangeWalkHistoryFormatError(str(exc)) from exc
        confirmed = _marker_tuple(data["confirmed_markers"], "confirmed_markers")
        if len(confirmed) != 5 or confirmed != selected:
            raise RangeWalkHistoryFormatError(
                "Confirmed markers do not match the saved candidate mapping."
            )
        direction = _nonempty_string(data["direction_used"], "direction_used")
        if direction not in {"higher", "lower"}:
            raise RangeWalkHistoryFormatError("Invalid detection direction.")
        recording_start = _datetime(data["recording_start"], "recording_start")
        recording_end = _datetime(data["recording_end"], "recording_end")
        if recording_end < recording_start:
            raise RangeWalkHistoryFormatError("Invalid recording time span.")
        return StoredWalk1Baseline(
            baseline_id,
            data["created_at_utc"],
            source_filename,
            original_path,
            source_sha256,
            (self.evidence_dir / stored_filename).resolve(),
            _nonempty_string(data["label"], "label"),
            _nonempty_string(data["antenna"], "antenna"),
            landmark_names,
            turnaround,
            settings,
            candidates,
            numbers,
            confirmed,
            direction,
            _nonempty_string(data["direction_assessment"], "direction_assessment"),
            recording_start,
            recording_end,
        )


def _marker_to_dict(marker: LandmarkMarker) -> dict[str, object]:
    return {
        "onset": marker.onset.isoformat(),
        "release": marker.release.isoformat(),
        "down_sample_count": marker.down_sample_count,
    }


def _marker_tuple(value: object, label: str) -> tuple[LandmarkMarker, ...]:
    if not isinstance(value, list):
        raise RangeWalkHistoryFormatError(f"{label} must be a list.")
    markers = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "onset",
            "release",
            "down_sample_count",
        }:
            raise RangeWalkHistoryFormatError(f"Invalid {label} marker.")
        onset = _datetime(item["onset"], f"{label} onset")
        release = _datetime(item["release"], f"{label} release")
        samples = item["down_sample_count"]
        if (
            release <= onset
            or isinstance(samples, bool)
            or not isinstance(samples, int)
            or samples <= 0
        ):
            raise RangeWalkHistoryFormatError(f"Invalid {label} marker bounds.")
        markers.append(LandmarkMarker(onset, release, samples))
    if any(
        later.onset <= earlier.release
        for earlier, later in zip(markers, markers[1:])
    ):
        raise RangeWalkHistoryFormatError(f"{label} must be chronological.")
    return tuple(markers)


def _optional_marker_tuple(
    value: object, label: str, length: int
) -> tuple[LandmarkMarker | None, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise RangeWalkHistoryFormatError(f"{label} must contain {length} entries.")
    markers = []
    for item in value:
        if item is None:
            markers.append(None)
        else:
            markers.append(_marker_tuple([item], label)[0])
    present = [marker for marker in markers if marker is not None]
    if any(
        later.onset <= earlier.release
        for earlier, later in zip(present, present[1:])
    ):
        raise RangeWalkHistoryFormatError(f"{label} must be chronological.")
    return tuple(markers)


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise RangeWalkHistoryFormatError(f"{label} must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RangeWalkHistoryFormatError(
            f"{label} must be an ISO timestamp."
        ) from exc
    return parsed


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RangeWalkHistoryFormatError(f"{label} must be a normalized string.")
    return value


def _record_identifier(value: object, label: str) -> str:
    identifier = _nonempty_string(value, label)
    if len(identifier) != 32 or any(
        character not in "0123456789abcdef" for character in identifier
    ):
        raise RangeWalkHistoryFormatError(f"Invalid {label}.")
    return identifier


def _optional_normalized_string(value: object, label: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise RangeWalkHistoryFormatError(f"{label} must be a string.")
    return value


def _filename(value: object) -> str:
    filename = _nonempty_string(value, "filename")
    if Path(filename).name != filename or any(char in filename for char in ("/", "\\")):
        raise RangeWalkHistoryFormatError("Invalid filename.")
    return filename


def _sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RangeWalkHistoryFormatError("Invalid CSV SHA-256.")
    return value


def _string_tuple(value: object, label: str, length: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise RangeWalkHistoryFormatError(f"{label} must contain {length} strings.")
    return tuple(_nonempty_string(item, label) for item in value)


def _integer_tuple(value: object, label: str, length: int) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise RangeWalkHistoryFormatError(f"{label} must contain {length} integers.")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise RangeWalkHistoryFormatError(f"{label} must contain integers.")
    return tuple(value)


def _optional_integer_tuple(
    value: object, label: str, length: int
) -> tuple[int | None, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise RangeWalkHistoryFormatError(f"{label} must contain {length} entries.")
    if any(
        item is not None and (isinstance(item, bool) or not isinstance(item, int))
        for item in value
    ):
        raise RangeWalkHistoryFormatError(
            f"{label} must contain integers or null values."
        )
    return tuple(value)


def _settings(value: object) -> WalkSettings:
    fields = {"tx_power", "packet_rate", "rf_mode", "dynamic_power"}
    if not isinstance(value, dict) or set(value) != fields:
        raise RangeWalkHistoryFormatError("Invalid RF settings.")
    return WalkSettings(
        *(
            _optional_normalized_string(value[field], field)
            for field in ("tx_power", "packet_rate", "rf_mode", "dynamic_power")
        )
    )


def _record_id(record) -> str:
    return getattr(record, "baseline_id", getattr(record, "walk_id", "unknown"))
