"""Versioned durable storage for Range-Walk Walk 1 baselines."""

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


HISTORY_SCHEMA_VERSION = 1
BASELINE_SCHEMA_VERSION = 1
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
    """The same source CSV is already owned by a saved baseline."""


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


def fingerprint_csv(path: str | Path) -> str:
    """Return the SHA-256 identity of one CSV file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RangeWalkHistoryStore:
    """Strict atomic persistence for independent Walk 1 baselines."""

    def __init__(
        self,
        path: str | Path = DEFAULT_HISTORY_PATH,
        evidence_dir: str | Path | None = None,
    ):
        self.path = Path(path)
        self.evidence_dir = Path(evidence_dir or DEFAULT_EVIDENCE_DIR)
        self._records: dict[str, StoredWalk1Baseline] = {}
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
            self._validate_managed_evidence(record)
        return self.records

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
            duplicate = next(
                (
                    record
                    for record in self._records.values()
                    if record.csv_sha256 == source_sha256
                ),
                None,
            )
            if duplicate is not None:
                raise DuplicateRangeWalkEvidenceError(
                    "CSV evidence is already saved by baseline "
                    f"{duplicate.baseline_id}."
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
        self._validate_managed_evidence(current)
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

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RangeWalkHistoryFormatError(
                f"Unable to read {self.path}: {exc}"
            ) from exc
        if not isinstance(data, dict) or set(data) != {"version", "baselines"}:
            raise RangeWalkHistoryFormatError(
                "Range-Walk history contains unexpected or missing fields."
            )
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise RangeWalkHistoryFormatError(
                "Range-Walk history version must be an integer."
            )
        if version != HISTORY_SCHEMA_VERSION:
            raise RangeWalkHistoryFormatError(
                f"Unsupported Range-Walk history version: {version}"
            )
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

    def _save(self, records: dict[str, StoredWalk1Baseline]) -> None:
        data = {
            "version": HISTORY_SCHEMA_VERSION,
            "baselines": {
                key: self._record_to_dict(records[key]) for key in sorted(records)
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

    def _validate_managed_evidence(self, record: StoredWalk1Baseline) -> None:
        expected = self.evidence_dir / f"{record.csv_sha256}.csv"
        if record.stored_csv_path != expected.resolve():
            raise RangeWalkHistoryFormatError(
                f"Managed CSV path is inconsistent for baseline {record.baseline_id}."
            )
        if not expected.is_file():
            raise RangeWalkHistoryError(
                f"Managed CSV is missing for baseline {record.baseline_id}: {expected}"
            )
        if fingerprint_csv(expected) != record.csv_sha256:
            raise RangeWalkHistoryError(
                f"Managed CSV checksum mismatch for baseline {record.baseline_id}."
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
