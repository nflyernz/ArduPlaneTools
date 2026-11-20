"""Isolated v2 battery evidence schema; no production ingestion or default path."""

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from datetime import timedelta
from pathlib import Path

from .battery_pack_history import (
    BatteryPackHistoryError,
    BatteryPackHistoryFormatError,
    _validate_finite,
    _validate_integer,
    _validate_recorded_at_utc,
    _validate_sha256,
)
from .gps_time import (
    GPS_WEEK_MILLISECONDS,
    SUPPORTED_GPS_UTC_OFFSETS,
    format_utc_milliseconds,
    gps_week_time_to_utc,
)
from .pilot_plateau_voltage import MIN_DURATION_US, PRE_RECENCY_US

STORE_VERSION = 2
OBSERVATION_VERSION = 2
SEMANTICS = "battery-load-v2"


def physical_event_id_for(*, source_sha256, battery_instance, flight_start_us,
                          flight_end_us, logged_takeoff_us):
    """Stable across measurement changes, within the same FlightWindow segmentation."""
    identity = ["physical-takeoff-v2", source_sha256, battery_instance,
                flight_start_us, flight_end_us, logged_takeoff_us]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def v2_observation_id_for(physical_event_id):
    return hashlib.sha256(json.dumps([physical_event_id, SEMANTICS],
                                     separators=(",", ":")).encode()).hexdigest()


def _strict_object(cls, data):
    if not isinstance(data, dict) or set(data) != {field.name for field in fields(cls)}:
        raise BatteryPackHistoryFormatError(f"Invalid {cls.__name__} fields.")
    return data


def _time(value, name):
    if value is not None:
        _validate_integer(value, name)


def _number(value, name):
    _validate_finite(value, name, optional=True)


def _status(value, name):
    if value not in ("qualified", "partial", "unavailable"):
        raise BatteryPackHistoryFormatError(f"Invalid {name}.")


@dataclass(frozen=True)
class LoadEvidenceV2:
    onset_status: str
    t0_us: int | None
    reference_status: str
    reference_current_a: float | None
    threshold_current_a: float | None
    t1_status: str
    t1_us: int | None
    peak_current_a: float | None
    minimum_loaded_voltage_v: float | None
    current_at_minimum_voltage_a: float | None
    voltage_drop_status: str
    baseline_voltage_v: float | None
    baseline_current_a: float | None
    qualified_voltage_drop_v: float | None
    recovery_status: str
    recovery_time_us: int | None
    recovery_voltage_v: float | None
    recovery_current_a: float | None
    limitations: tuple[str, ...]

    @classmethod
    def from_dict(cls, data):
        values = dict(_strict_object(cls, data))
        if not isinstance(values["limitations"], list):
            raise BatteryPackHistoryFormatError("limitations must be a list.")
        values["limitations"] = tuple(values["limitations"])
        result = cls(**values)
        result.validate()
        return result

    def validate(self):
        for name in ("onset_status", "reference_status", "t1_status",
                     "voltage_drop_status", "recovery_status"):
            _status(getattr(self, name), name)
        if (not isinstance(self.limitations, tuple)
                or any(not isinstance(item, str) or not item.strip()
                       for item in self.limitations)):
            raise BatteryPackHistoryFormatError("Invalid load limitations.")
        if any(getattr(self, name) != "qualified" for name in (
                "onset_status", "reference_status", "t1_status",
                "voltage_drop_status", "recovery_status")) and not self.limitations:
            raise BatteryPackHistoryFormatError("Unqualified load evidence needs a limitation.")
        for name in ("t0_us", "t1_us", "recovery_time_us"):
            _time(getattr(self, name), name)
        for name in ("reference_current_a", "threshold_current_a", "peak_current_a",
                     "minimum_loaded_voltage_v", "current_at_minimum_voltage_a",
                     "baseline_voltage_v", "baseline_current_a",
                     "qualified_voltage_drop_v", "recovery_voltage_v",
                     "recovery_current_a"):
            _number(getattr(self, name), name)
        if (self.onset_status == "qualified") != (self.t0_us is not None):
            raise BatteryPackHistoryFormatError("Qualified onset requires T0 only.")
        if self.reference_status == "qualified":
            if self.t0_us is None or self.reference_current_a is None or self.threshold_current_a is None:
                raise BatteryPackHistoryFormatError("Qualified current reference is incomplete.")
            if (self.reference_current_a <= 0 or self.threshold_current_a <= 0
                    or self.threshold_current_a > self.reference_current_a):
                raise BatteryPackHistoryFormatError("Invalid current reference.")
        elif self.reference_current_a is not None or self.threshold_current_a is not None:
            raise BatteryPackHistoryFormatError("Unqualified reference has numerical values.")
        if (self.t1_status == "qualified") != (self.t1_us is not None):
            raise BatteryPackHistoryFormatError("T1 status and timestamp disagree.")
        if self.t1_us is not None and (self.t0_us is None or self.t1_us <= self.t0_us
                                       or self.reference_status != "qualified"):
            raise BatteryPackHistoryFormatError("T1 needs a preceding qualified reference.")
        if self.voltage_drop_status == "qualified":
            if any(value is None for value in (self.t0_us, self.baseline_voltage_v,
                    self.baseline_current_a, self.minimum_loaded_voltage_v,
                    self.qualified_voltage_drop_v)):
                raise BatteryPackHistoryFormatError("Qualified voltage drop is incomplete.")
            if not math.isclose(self.qualified_voltage_drop_v,
                                self.baseline_voltage_v - self.minimum_loaded_voltage_v,
                                rel_tol=0, abs_tol=1e-6):
                raise BatteryPackHistoryFormatError("Qualified drop does not match voltages.")
        elif any(value is not None for value in (self.baseline_voltage_v,
                 self.baseline_current_a, self.qualified_voltage_drop_v)):
            raise BatteryPackHistoryFormatError("Unqualified voltage drop has baseline values.")
        if self.recovery_status == "qualified":
            if any(value is None for value in (self.recovery_time_us,
                    self.recovery_voltage_v, self.recovery_current_a)):
                raise BatteryPackHistoryFormatError("Qualified recovery is incomplete.")
        elif any(value is not None for value in (self.recovery_time_us,
                 self.recovery_voltage_v, self.recovery_current_a)):
            raise BatteryPackHistoryFormatError("Unqualified recovery has numerical values.")
        if self.recovery_status == "qualified" and (self.t1_status != "qualified"
                or self.t1_us is None or self.recovery_time_us <= self.t1_us):
            raise BatteryPackHistoryFormatError("Qualified recovery must follow qualified T1.")
        for name in ("reference_current_a", "threshold_current_a", "peak_current_a",
                     "minimum_loaded_voltage_v", "current_at_minimum_voltage_a",
                     "baseline_voltage_v", "baseline_current_a", "recovery_voltage_v",
                     "recovery_current_a"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise BatteryPackHistoryFormatError(f"{name} cannot be negative.")


@dataclass(frozen=True)
class PlateauEvidenceV2:
    status: str
    pre_start_us: int | None
    pre_end_us: int | None
    pre_voltage_v: float | None
    pre_current_a: float | None
    loaded_start_us: int | None
    loaded_end_us: int | None
    loaded_voltage_v: float | None
    loaded_current_a: float | None
    observed_voltage_change_v: float | None
    current_change_a: float | None
    limitation: str | None

    @classmethod
    def from_dict(cls, data):
        result = cls(**_strict_object(cls, data))
        result.validate()
        return result

    def validate(self):
        _status(self.status, "plateau status")
        times = ("pre_start_us", "pre_end_us", "loaded_start_us", "loaded_end_us")
        numbers = ("pre_voltage_v", "pre_current_a", "loaded_voltage_v",
                   "loaded_current_a", "observed_voltage_change_v", "current_change_a")
        for name in times:
            _time(getattr(self, name), name)
        for name in numbers:
            _number(getattr(self, name), name)
        values = [getattr(self, name) for name in (*times, *numbers)]
        if self.status == "qualified":
            if any(value is None for value in values) or self.limitation is not None:
                raise BatteryPackHistoryFormatError("Qualified plateau evidence is incomplete.")
            if not (self.pre_start_us < self.pre_end_us < self.loaded_start_us
                    < self.loaded_end_us):
                raise BatteryPackHistoryFormatError("Plateau intervals overlap or reverse.")
            if (self.pre_end_us - self.pre_start_us < MIN_DURATION_US
                    or self.loaded_end_us - self.loaded_start_us < MIN_DURATION_US):
                raise BatteryPackHistoryFormatError("Qualified plateau interval is too short.")
            if self.loaded_current_a <= self.pre_current_a:
                raise BatteryPackHistoryFormatError("Loaded current must be higher.")
            if not math.isclose(self.observed_voltage_change_v,
                                self.pre_voltage_v - self.loaded_voltage_v,
                                rel_tol=0, abs_tol=1e-6) or not math.isclose(
                    self.current_change_a, self.loaded_current_a - self.pre_current_a,
                    rel_tol=0, abs_tol=1e-6):
                raise BatteryPackHistoryFormatError("Plateau differences do not match medians.")
        elif (any(value is not None for value in values)
              or not isinstance(self.limitation, str) or not self.limitation.strip()):
            raise BatteryPackHistoryFormatError("Unqualified plateau needs a reason, not values.")


@dataclass(frozen=True)
class BatteryPackObservationV2:
    observation_schema_version: int
    analysis_semantics_version: str
    physical_event_id: str
    observation_id: str
    source_sha256: str
    source_filename: str
    pack_id_at_ingest: str
    battery_instance: int
    flight_number: int
    flight_start_us: int
    flight_end_us: int
    takeoff_type: str
    flight_mode: str
    logged_takeoff_us: int
    recorded_at_utc: str | None
    gps_anchor_week: int | None
    gps_anchor_week_ms: int | None
    gps_anchor_time_us: int | None
    gps_instance: int | None
    gps_utc_offset_seconds: int | None
    physical_contact_inferred: bool
    load: LoadEvidenceV2
    plateau: PlateauEvidenceV2

    def to_dict(self):
        self.validate()
        result = asdict(self)
        result["load"]["limitations"] = list(self.load.limitations)
        return result

    @classmethod
    def from_dict(cls, data):
        values = dict(_strict_object(cls, data))
        values["load"] = LoadEvidenceV2.from_dict(values["load"])
        values["plateau"] = PlateauEvidenceV2.from_dict(values["plateau"])
        result = cls(**values)
        result.validate()
        return result

    def validate(self):
        if type(self.observation_schema_version) is not int or self.observation_schema_version != OBSERVATION_VERSION:
            raise BatteryPackHistoryFormatError("Unsupported v2 observation schema.")
        if self.analysis_semantics_version != SEMANTICS:
            raise BatteryPackHistoryFormatError("Unsupported v2 analysis semantics.")
        for name in ("physical_event_id", "observation_id", "source_sha256"):
            _validate_sha256(getattr(self, name), name)
        if (not isinstance(self.source_filename, str) or not self.source_filename
                or Path(self.source_filename).name != self.source_filename
                or "\\" in self.source_filename):
            raise BatteryPackHistoryFormatError("Invalid source filename.")
        if (not isinstance(self.pack_id_at_ingest, str) or not self.pack_id_at_ingest.strip()
                or self.pack_id_at_ingest != self.pack_id_at_ingest.strip()):
            raise BatteryPackHistoryFormatError("Invalid original pack ownership.")
        for name in ("battery_instance", "flight_number", "flight_start_us",
                     "flight_end_us", "logged_takeoff_us"):
            _validate_integer(getattr(self, name), name)
        if (self.flight_number < 1 or self.flight_start_us >= self.flight_end_us
                or not self.flight_start_us <= self.logged_takeoff_us <= self.flight_end_us):
            raise BatteryPackHistoryFormatError("Invalid FlightWindow or takeoff time.")
        if (self.takeoff_type, self.flight_mode) not in (("AUTO", "AUTO"),
                ("PILOT_CONTROLLED", "MANUAL"), ("PILOT_CONTROLLED", "FBWA")):
            raise BatteryPackHistoryFormatError("Invalid takeoff classification/mode.")
        if self.physical_contact_inferred is not True:
            raise BatteryPackHistoryFormatError("Telemetry contact inference must be explicit.")
        self.load.validate()
        self.plateau.validate()
        if self.load.t0_us is not None and not (self.flight_start_us - 8_000_000
                <= self.load.t0_us <= self.flight_end_us):
            raise BatteryPackHistoryFormatError("T0 outside supported event context.")
        for name in ("t1_us", "recovery_time_us"):
            value = getattr(self.load, name)
            if value is not None and value > self.flight_end_us:
                raise BatteryPackHistoryFormatError(f"{name} exceeds FlightWindow.")
        if (self.plateau.status == "qualified"
                and (self.load.onset_status != "qualified"
                     or self.load.reference_status != "qualified"
                     or self.load.t0_us is None
                     or not 0 < self.load.t0_us - self.plateau.pre_end_us <= PRE_RECENCY_US
                     or self.plateau.loaded_start_us < self.load.t0_us
                     or self.plateau.loaded_end_us > self.load.t0_us + 6_000_000
                     or self.plateau.loaded_end_us > self.flight_end_us
                     or self.load.t1_us is not None and self.plateau.loaded_end_us > self.load.t1_us
                     or self.plateau.loaded_current_a < max(
                         self.plateau.pre_current_a + 5.0,
                         0.70 * self.load.reference_current_a))):
            raise BatteryPackHistoryFormatError("Plateau interval is outside T0/T1/flight bounds.")
        gps = (self.gps_anchor_week, self.gps_anchor_week_ms, self.gps_anchor_time_us,
               self.gps_instance, self.gps_utc_offset_seconds)
        if self.recorded_at_utc is None:
            if any(value is not None for value in gps):
                raise BatteryPackHistoryFormatError("Partial GPS provenance without UTC.")
        else:
            if any(value is None for value in gps):
                raise BatteryPackHistoryFormatError("UTC requires complete GPS provenance.")
            _validate_recorded_at_utc(self.recorded_at_utc)
            for name in ("gps_anchor_week", "gps_anchor_week_ms", "gps_anchor_time_us",
                         "gps_instance", "gps_utc_offset_seconds"):
                _validate_integer(getattr(self, name), name)
            if (self.gps_anchor_week <= 0 or not 0 <= self.gps_anchor_week_ms < GPS_WEEK_MILLISECONDS
                    or self.gps_utc_offset_seconds not in SUPPORTED_GPS_UTC_OFFSETS
                    or self.gps_anchor_time_us > self.logged_takeoff_us):
                raise BatteryPackHistoryFormatError("Invalid GPS provenance.")
            expected = format_utc_milliseconds(gps_week_time_to_utc(
                self.gps_anchor_week, self.gps_anchor_week_ms,
                self.gps_utc_offset_seconds) + timedelta(
                    microseconds=self.logged_takeoff_us - self.gps_anchor_time_us))
            if self.recorded_at_utc != expected:
                raise BatteryPackHistoryFormatError("UTC does not match GPS provenance.")
        expected_id = physical_event_id_for(
            source_sha256=self.source_sha256, battery_instance=self.battery_instance,
            flight_start_us=self.flight_start_us, flight_end_us=self.flight_end_us,
            logged_takeoff_us=self.logged_takeoff_us)
        if self.physical_event_id != expected_id or self.observation_id != v2_observation_id_for(expected_id):
            raise BatteryPackHistoryFormatError("V2 identity does not match provenance.")


class BatteryPackHistoryV2Store:
    """Explicit-path isolated store for Stage 1 tests; not wired into ingestion."""

    def __init__(self, path):
        self.path = Path(path)
        self._observations = {}
        self._load()

    @property
    def observations(self):
        return tuple(self._observations[key] for key in sorted(self._observations))

    def _load(self):
        if not self.path.exists():
            self._observations = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BatteryPackHistoryFormatError("Cannot read v2 history.") from exc
        if (not isinstance(data, dict) or set(data) != {"version", "observations"}
                or type(data["version"]) is not int or data["version"] != STORE_VERSION
                or not isinstance(data["observations"], dict)):
            raise BatteryPackHistoryFormatError("Invalid v2 history envelope.")
        loaded = {}
        for key, raw in data["observations"].items():
            observation = BatteryPackObservationV2.from_dict(raw)
            if key != observation.observation_id:
                raise BatteryPackHistoryFormatError("V2 observation map key mismatch.")
            loaded[key] = observation
        self._observations = loaded

    def add_observations(self, observations):
        candidate = dict(self._observations)
        added = 0
        for observation in observations:
            if not isinstance(observation, BatteryPackObservationV2):
                raise BatteryPackHistoryFormatError("Only v2 observations are supported.")
            observation.validate()
            old = candidate.get(observation.observation_id)
            if old is not None:
                if not _same_analytical_evidence(old, observation):
                    raise BatteryPackHistoryError("Conflicting evidence for v2 observation ID.")
                continue
            candidate[observation.observation_id] = observation
            added += 1
        if added:
            self._save(candidate)
        return added

    def _save(self, observations):
        data = {"version": STORE_VERSION, "observations": {
            key: observations[key].to_dict() for key in sorted(observations)}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            descriptor, name = tempfile.mkstemp(dir=self.path.parent,
                                                prefix=f".{self.path.name}.", suffix=".tmp")
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._observations = dict(observations)


def _same_analytical_evidence(existing, incoming):
    """Keep first ingest provenance while comparing all analytical evidence."""
    before = existing.to_dict()
    after = incoming.to_dict()
    for name in ("source_filename", "pack_id_at_ingest"):
        before.pop(name)
        after.pop(name)
    return before == after
