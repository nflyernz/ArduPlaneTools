"""Durable AUTO-takeoff evidence for physical battery packs."""

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from numbers import Real
from pathlib import Path

from .application_data import application_data_directory
from .gps_time import (
    GPS_WEEK_MILLISECONDS,
    SUPPORTED_GPS_UTC_OFFSETS,
    format_utc_milliseconds,
    gps_week_time_to_utc,
)

HISTORY_SCHEMA_VERSION = 1
OBSERVATION_SCHEMA_VERSION = 1
ANALYSIS_SEMANTICS_VERSION = "battery-load-v1"
SUPPORTED_ANALYSIS_SEMANTICS = (ANALYSIS_SEMANTICS_VERSION,)
DEFAULT_HISTORY_PATH = (
    application_data_directory() / "battery_pack_history.json"
)


class BatteryPackHistoryError(ValueError):
    """Base error for invalid battery-history persistence operations."""


class BatteryPackHistoryFormatError(BatteryPackHistoryError):
    """Persistent battery history does not match the supported schema."""


@dataclass(frozen=True)
class BatteryPackObservation:
    """One versioned durable AUTO takeoff observation."""

    event_key: str
    observation_id: str
    observation_schema_version: int
    analysis_semantics_version: str
    pack_id_at_ingest: str
    source_sha256: str
    source_filename: str
    firmware: str | None
    recorded_at_utc: str | None
    gps_anchor_week: int | None
    gps_anchor_week_ms: int | None
    gps_anchor_time_us: int | None
    gps_instance: int | None
    gps_utc_offset_seconds: int | None
    flight_number: int
    flight_start_us: int
    flight_end_us: int
    battery_instance: int
    event_type: str
    takeoff_type: str
    event_start_us: int
    event_end_us: int
    event_duration_s: float
    capacity_used_mah: float | None
    pre_load_voltage_v: float | None
    minimum_loaded_voltage_v: float | None
    peak_current_a: float | None
    average_current_a: float | None
    current_at_minimum_voltage_a: float | None
    maximum_throttle_pct: float | None
    average_throttle_pct: float | None
    recovery_time_us: int | None
    voltage_after_recovery_v: float | None
    voltage_sag_v: float | None
    voltage_recovery_v: float | None
    low_voltage_margin_v: float | None
    critical_voltage_margin_v: float | None
    configuration_lookup_time_us: int | None
    configured_capacity_mah: float | None
    configured_low_voltage_v: float | None
    configured_critical_voltage_v: float | None
    configured_failsafe_voltage_source: float | None
    configuration_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the strict JSON representation."""
        data = asdict(self)
        data["configuration_warnings"] = list(self.configuration_warnings)
        return data

    @classmethod
    def from_dict(cls, data: object) -> "BatteryPackObservation":
        """Validate and reconstruct one persisted observation."""
        if not isinstance(data, dict):
            raise BatteryPackHistoryFormatError("Observation must be an object.")
        expected = {field.name for field in fields(cls)}
        if set(data) != expected:
            raise BatteryPackHistoryFormatError(
                "Observation contains unexpected or missing fields."
            )

        values = dict(data)
        warnings = values["configuration_warnings"]
        if not isinstance(warnings, list) or not all(
            isinstance(warning, str) for warning in warnings
        ):
            raise BatteryPackHistoryFormatError(
                "configuration_warnings must be a list of strings."
            )
        values["configuration_warnings"] = tuple(warnings)
        observation = cls(**values)
        observation.validate()
        return observation

    def validate(self) -> None:
        """Validate identity, provenance, bounds, and finite measurements."""
        _validate_integer(
            self.observation_schema_version,
            "observation_schema_version",
        )
        if self.observation_schema_version != OBSERVATION_SCHEMA_VERSION:
            raise BatteryPackHistoryFormatError(
                "Unsupported observation schema version: "
                f"{self.observation_schema_version}"
            )
        if self.analysis_semantics_version not in SUPPORTED_ANALYSIS_SEMANTICS:
            raise BatteryPackHistoryFormatError(
                "Unsupported battery analysis semantics: "
                f"{self.analysis_semantics_version}"
            )
        _validate_sha256(self.source_sha256, "source SHA-256")
        _validate_sha256(self.event_key, "event key")
        _validate_sha256(self.observation_id, "observation ID")
        for name, value in (
            ("pack_id_at_ingest", self.pack_id_at_ingest),
            ("source_filename", self.source_filename),
            ("event_type", self.event_type),
            ("takeoff_type", self.takeoff_type),
        ):
            if not isinstance(value, str) or not value.strip():
                raise BatteryPackHistoryFormatError(f"{name} must be non-empty.")
        if self.pack_id_at_ingest != self.pack_id_at_ingest.strip():
            raise BatteryPackHistoryFormatError(
                "pack_id_at_ingest must already be normalized."
            )
        if self.firmware is not None and not isinstance(self.firmware, str):
            raise BatteryPackHistoryFormatError("firmware must be a string or null.")
        if Path(self.source_filename).name != self.source_filename or any(
            separator in self.source_filename for separator in ("/", "\\")
        ):
            raise BatteryPackHistoryFormatError(
                "source_filename must contain a filename only."
            )
        if self.event_type != "TAKEOFF":
            raise BatteryPackHistoryFormatError("Only TAKEOFF history is supported.")
        if self.takeoff_type != "AUTO":
            raise BatteryPackHistoryFormatError(
                "Only AUTO takeoff history is supported."
            )
        if not isinstance(self.configuration_warnings, tuple) or not all(
            isinstance(warning, str) for warning in self.configuration_warnings
        ):
            raise BatteryPackHistoryFormatError(
                "configuration_warnings must be a tuple of strings."
            )

        integer_fields = {
            "flight_number": self.flight_number,
            "flight_start_us": self.flight_start_us,
            "flight_end_us": self.flight_end_us,
            "battery_instance": self.battery_instance,
            "event_start_us": self.event_start_us,
            "event_end_us": self.event_end_us,
        }
        for name, value in integer_fields.items():
            _validate_integer(value, name)
        if self.flight_number < 1 or self.battery_instance < 0:
            raise BatteryPackHistoryFormatError(
                "Flight number and battery instance are invalid."
            )
        if not (
            self.flight_start_us
            <= self.event_start_us
            <= self.event_end_us
            <= self.flight_end_us
        ):
            raise BatteryPackHistoryFormatError(
                "Event bounds must lie inside the FlightWindow."
            )

        _validate_finite(self.event_duration_s, "event_duration_s", optional=False)
        if self.event_duration_s < 0:
            raise BatteryPackHistoryFormatError(
                "event_duration_s must be non-negative."
            )
        expected_duration_s = (
            self.event_end_us - self.event_start_us
        ) / 1_000_000
        if not math.isclose(
            self.event_duration_s,
            expected_duration_s,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise BatteryPackHistoryFormatError(
                "event_duration_s does not match the event bounds."
            )
        for name in _OPTIONAL_FLOAT_FIELDS:
            _validate_finite(getattr(self, name), name, optional=True)
        for name in ("recovery_time_us", "configuration_lookup_time_us"):
            value = getattr(self, name)
            if value is not None:
                _validate_integer(value, name)
        if self.recovery_time_us is not None and not (
            self.event_end_us <= self.recovery_time_us <= self.flight_end_us
        ):
            raise BatteryPackHistoryFormatError(
                "recovery_time_us must follow the event inside the FlightWindow."
            )

        gps_values = (
            self.gps_anchor_week,
            self.gps_anchor_week_ms,
            self.gps_anchor_time_us,
            self.gps_instance,
            self.gps_utc_offset_seconds,
        )
        if self.recorded_at_utc is None:
            if any(value is not None for value in gps_values):
                raise BatteryPackHistoryFormatError(
                    "Unavailable UTC must not retain partial GPS provenance."
                )
        else:
            if any(value is None for value in gps_values):
                raise BatteryPackHistoryFormatError(
                    "UTC evidence requires complete GPS provenance."
                )
            _validate_recorded_at_utc(self.recorded_at_utc)
            for name, value in (
                ("gps_anchor_week", self.gps_anchor_week),
                ("gps_anchor_week_ms", self.gps_anchor_week_ms),
                ("gps_anchor_time_us", self.gps_anchor_time_us),
                ("gps_instance", self.gps_instance),
                ("gps_utc_offset_seconds", self.gps_utc_offset_seconds),
            ):
                _validate_integer(value, name)
            if self.gps_anchor_week <= 0 or not (
                0 <= self.gps_anchor_week_ms < GPS_WEEK_MILLISECONDS
            ):
                raise BatteryPackHistoryFormatError("Invalid GPS week evidence.")
            if self.gps_utc_offset_seconds not in SUPPORTED_GPS_UTC_OFFSETS:
                raise BatteryPackHistoryFormatError(
                    "Unsupported GPS-to-UTC offset."
                )
            if self.gps_anchor_time_us > self.event_start_us:
                raise BatteryPackHistoryFormatError(
                    "GPS anchor must be causal to the event start."
                )
            expected_recorded_at = format_utc_milliseconds(
                gps_week_time_to_utc(
                    self.gps_anchor_week,
                    self.gps_anchor_week_ms,
                    self.gps_utc_offset_seconds,
                )
                + timedelta(
                    microseconds=self.event_start_us - self.gps_anchor_time_us
                )
            )
            if self.recorded_at_utc != expected_recorded_at:
                raise BatteryPackHistoryFormatError(
                    "recorded_at_utc does not match its GPS provenance."
                )

        expected_event_key = event_key_for(
            source_sha256=self.source_sha256,
            battery_instance=self.battery_instance,
            flight_start_us=self.flight_start_us,
            flight_end_us=self.flight_end_us,
            event_type=self.event_type,
            takeoff_type=self.takeoff_type,
            event_start_us=self.event_start_us,
            event_end_us=self.event_end_us,
        )
        if self.event_key != expected_event_key:
            raise BatteryPackHistoryFormatError("Event key does not match evidence.")
        if self.observation_id != observation_id_for(
            self.event_key,
            self.analysis_semantics_version,
        ):
            raise BatteryPackHistoryFormatError(
                "Observation ID does not match event/version evidence."
            )


_OPTIONAL_FLOAT_FIELDS = (
    "capacity_used_mah",
    "pre_load_voltage_v",
    "minimum_loaded_voltage_v",
    "peak_current_a",
    "average_current_a",
    "current_at_minimum_voltage_a",
    "maximum_throttle_pct",
    "average_throttle_pct",
    "voltage_after_recovery_v",
    "voltage_sag_v",
    "voltage_recovery_v",
    "low_voltage_margin_v",
    "critical_voltage_margin_v",
    "configured_capacity_mah",
    "configured_low_voltage_v",
    "configured_critical_voltage_v",
    "configured_failsafe_voltage_source",
)


def event_key_for(**identity: object) -> str:
    """Return a deterministic key for one physical logged event."""
    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def observation_id_for(event_key: str, semantics_version: str) -> str:
    """Return the deterministic identity of one analyzed event version."""
    canonical = json.dumps(
        [event_key, semantics_version],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class BatteryPackHistoryStore:
    """Strict atomic JSON persistence for battery Pack observations."""

    def __init__(self, path: str | Path = DEFAULT_HISTORY_PATH):
        self.path = Path(path)
        self._observations: dict[str, BatteryPackObservation] = {}
        self._load()

    @property
    def observations(self) -> tuple[BatteryPackObservation, ...]:
        """Return observations in deterministic ID order."""
        return tuple(
            self._observations[key] for key in sorted(self._observations)
        )

    def add_observations(
        self,
        observations: list[BatteryPackObservation],
    ) -> int:
        """Atomically add an idempotent batch and return the new row count."""
        candidate = dict(self._observations)
        added = 0
        for observation in observations:
            observation.validate()
            existing = candidate.get(observation.observation_id)
            if existing is not None:
                if not _same_analysis_evidence(existing, observation):
                    raise BatteryPackHistoryError(
                        "Conflicting evidence for observation ID: "
                        f"{observation.observation_id}"
                    )
                continue
            candidate[observation.observation_id] = observation
            added += 1

        if added:
            self._save(candidate)
        return added

    def newest_supported_observations(
        self,
    ) -> tuple[BatteryPackObservation, ...]:
        """Return the newest supported semantics for each physical event."""
        rank = {
            version: index
            for index, version in enumerate(SUPPORTED_ANALYSIS_SEMANTICS)
        }
        latest: dict[str, BatteryPackObservation] = {}
        for observation in self.observations:
            current = latest.get(observation.event_key)
            if current is None or rank[observation.analysis_semantics_version] > rank[
                current.analysis_semantics_version
            ]:
                latest[observation.event_key] = observation
        return tuple(latest[key] for key in sorted(latest))

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BatteryPackHistoryFormatError(
                f"Unable to read {self.path}: {exc}"
            ) from exc
        if not isinstance(data, dict) or set(data) != {"version", "observations"}:
            raise BatteryPackHistoryFormatError(
                "Battery history contains unexpected or missing fields."
            )
        version = data["version"]
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != HISTORY_SCHEMA_VERSION
        ):
            raise BatteryPackHistoryFormatError(
                f"Unsupported battery history version: {version}"
            )
        raw_observations = data["observations"]
        if not isinstance(raw_observations, dict):
            raise BatteryPackHistoryFormatError("observations must be an object.")
        observations = {}
        for observation_id, raw_observation in raw_observations.items():
            observation = BatteryPackObservation.from_dict(raw_observation)
            if observation_id != observation.observation_id:
                raise BatteryPackHistoryFormatError(
                    "Observation map key does not match observation ID."
                )
            observations[observation_id] = observation
        self._observations = observations

    def _save(
        self,
        observations: dict[str, BatteryPackObservation],
    ) -> None:
        data = {
            "version": HISTORY_SCHEMA_VERSION,
            "observations": {
                key: observations[key].to_dict() for key in sorted(observations)
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
                json.dump(
                    data,
                    store_file,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                store_file.write("\n")
                store_file.flush()
                os.fsync(store_file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        self._observations = observations


def _validate_sha256(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BatteryPackHistoryFormatError(f"Invalid {label}.")


def _same_analysis_evidence(
    existing: BatteryPackObservation,
    incoming: BatteryPackObservation,
) -> bool:
    """Ignore mutable filename/ownership provenance during reingestion."""
    existing_data = existing.to_dict()
    incoming_data = incoming.to_dict()
    for field_name in ("pack_id_at_ingest", "source_filename"):
        existing_data.pop(field_name)
        incoming_data.pop(field_name)
    return existing_data == incoming_data


def _validate_integer(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BatteryPackHistoryFormatError(f"{label} must be a non-negative integer.")


def _validate_finite(value: object, label: str, *, optional: bool) -> None:
    if optional and value is None:
        return
    if (
        not isinstance(value, Real)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise BatteryPackHistoryFormatError(f"{label} must be finite.")


def _validate_recorded_at_utc(value: object) -> None:
    if not isinstance(value, str):
        raise BatteryPackHistoryFormatError(
            "recorded_at_utc must be an ISO-8601 UTC string."
        )
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BatteryPackHistoryFormatError(
            "recorded_at_utc must be an ISO-8601 timestamp."
        ) from exc
    if timestamp.tzinfo != timezone.utc:
        raise BatteryPackHistoryFormatError("recorded_at_utc must use UTC.")
    if value != format_utc_milliseconds(timestamp):
        raise BatteryPackHistoryFormatError(
            "recorded_at_utc must use canonical millisecond UTC format."
        )
