"""Native-time evidence records and exploratory rules for FBWA stall tests."""

from bisect import bisect_right
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
import math

from .flight_window import FlightWindow


class StallStatus(str, Enum):
    PROBABLE_DEPARTURE = "probable_departure"
    NO_DEMONSTRATED_DEPARTURE = "no_demonstrated_departure"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class StallReason(str, Enum):
    SHORT_MOVEMENT = "short_movement"
    NO_SLOW_FLIGHT = "no_slow_flight"
    NOT_ARMED = "not_armed"
    UNKNOWN_ARMED_STATE = "unknown_armed_state"
    NOT_FBWA = "not_fbwa"
    MISSING_PITCH_INPUT = "missing_pitch_input"
    MISSING_TARGET = "missing_target"
    MISSING_AIRSPEED = "missing_airspeed"
    UNHEALTHY_AIRSPEED = "unhealthy_airspeed"
    EVIDENCE_GAP = "evidence_gap"
    PILOT_RELEASE = "pilot_release"
    MODE_BOUNDARY = "mode_boundary"
    FLIGHT_BOUNDARY = "flight_boundary"
    MISSING_ELEVATOR_MAPPING = "missing_elevator_mapping"
    MISSING_COMMAND_ENDPOINT = "missing_command_endpoint"
    MISSING_OUTPUT_ENDPOINT = "missing_output_endpoint"
    ENDPOINT_WITHOUT_FALL = "endpoint_without_fall"
    TRUNCATED_DIVERGENCE = "truncated_divergence"
    TARGET_RELAXED = "target_relaxed"
    NO_OPPOSED_FALL = "no_opposed_fall"


@dataclass(frozen=True, slots=True, order=True)
class EvidencePoint:
    """One logged field; source order disambiguates equal-time records."""

    time_us: int
    source_order: int
    source: str = dataclass_field(compare=False)
    field: str = dataclass_field(compare=False)
    value: float = dataclass_field(compare=False)


@dataclass(frozen=True, slots=True)
class TimedRow:
    time_us: int
    source_order: int
    source: str
    values: dict

    def point(self, field_name):
        value = number(self.values.get(field_name))
        if value is None:
            return None
        return EvidencePoint(
            self.time_us, self.source_order, self.source, field_name, value,
        )


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def rows(log, source):
    """Retain only records with usable native time and source ordering."""
    result = []
    for record in log.get(source).to_dict("records"):
        time = number(record.get("TimeUS"))
        order = number(record.get("_SourceOrder"))
        if time is None or order is None or time < 0:
            continue
        if not time.is_integer() or not order.is_integer():
            continue
        result.append(TimedRow(int(time), int(order), source, record))
    return sorted(result, key=lambda row: (row.time_us, row.source_order))


class RowIndex:
    """Bounded preceding lookup without time interpolation."""

    def __init__(self, values):
        self.values = values
        self.keys = [(row.time_us, row.source_order) for row in values]

    def before(self, time_us, source_order=math.inf, max_gap_us=None):
        index = bisect_right(self.keys, (time_us, source_order)) - 1
        if index < 0:
            return None
        row = self.values[index]
        if max_gap_us is not None and time_us - row.time_us > max_gap_us:
            return None
        return row


@dataclass(frozen=True, slots=True)
class StallRules:
    version: str
    association_max_us: int
    attitude_max_gap_us: int
    airspeed_max_gap_us: int
    minimum_pull_us: int
    release_reset_us: int
    partial_reset_us: int
    partial_reset_fraction: float
    reapply_input_rise_pwm: float
    reapply_target_rise_deg: float
    nose_up_input_pwm: float
    nose_up_target_deg: float
    minimum_relative_speed_drop_m_s: float
    speed_lookback_us: int
    fall_window_us: int
    local_peak_lookback_us: int
    local_peak_tolerance_deg: float
    minimum_pitch_fall_deg: float
    minimum_error_growth_deg: float
    maximum_target_relax_deg: float
    maximum_input_relax_pwm: float
    endpoint_window_before_us: int
    endpoint_window_after_us: int
    aetr_full_scale: float
    endpoint_nearness_fraction: float
    approximately_level_bank_deg: float
    idle_throttle_percent: float
    recovery_followup_us: int
    recovery_power_increase_percent: float
    recovery_speed_increase_m_s: float
    airspeed_health_probability_min: float
    airspeed_excursion_factor: float

    @classmethod
    def from_config(cls, config):
        def seconds(name):
            return round(float(config.get(f"stall.{name}")) * 1_000_000)

        def value(name):
            return float(config.get(f"stall.{name}"))

        rules = cls(
            version=str(config.get("analysis.rule_version")),
            association_max_us=seconds("association_max_s"),
            attitude_max_gap_us=seconds("attitude_max_gap_s"),
            airspeed_max_gap_us=seconds("airspeed_max_gap_s"),
            minimum_pull_us=seconds("minimum_pull_s"),
            release_reset_us=seconds("release_reset_s"),
            partial_reset_us=seconds("partial_reset_s"),
            partial_reset_fraction=value("partial_reset_fraction"),
            reapply_input_rise_pwm=value("reapply_input_rise_pwm"),
            reapply_target_rise_deg=value("reapply_target_rise_deg"),
            nose_up_input_pwm=value("nose_up_input_pwm"),
            nose_up_target_deg=value("nose_up_target_deg"),
            minimum_relative_speed_drop_m_s=value(
                "minimum_relative_speed_drop_m_s"
            ),
            speed_lookback_us=seconds("speed_lookback_s"),
            fall_window_us=seconds("fall_window_s"),
            local_peak_lookback_us=seconds("local_peak_lookback_s"),
            local_peak_tolerance_deg=value("local_peak_tolerance_deg"),
            minimum_pitch_fall_deg=value("minimum_pitch_fall_deg"),
            minimum_error_growth_deg=value("minimum_error_growth_deg"),
            maximum_target_relax_deg=value("maximum_target_relax_deg"),
            maximum_input_relax_pwm=value("maximum_input_relax_pwm"),
            endpoint_window_before_us=seconds("endpoint_window_before_s"),
            endpoint_window_after_us=seconds("endpoint_window_after_s"),
            aetr_full_scale=value("aetr_full_scale"),
            endpoint_nearness_fraction=value("endpoint_nearness_fraction"),
            approximately_level_bank_deg=value("approximately_level_bank_deg"),
            idle_throttle_percent=value("idle_throttle_percent"),
            recovery_followup_us=seconds("recovery_followup_s"),
            recovery_power_increase_percent=value(
                "recovery_power_increase_percent"
            ),
            recovery_speed_increase_m_s=value("recovery_speed_increase_m_s"),
            airspeed_health_probability_min=value(
                "airspeed_health_probability_min"
            ),
            airspeed_excursion_factor=value("airspeed_excursion_factor"),
        )
        if not rules.version or any(
            value <= 0 for value in (
                rules.association_max_us, rules.attitude_max_gap_us,
                rules.airspeed_max_gap_us, rules.minimum_pull_us,
                rules.release_reset_us, rules.partial_reset_us,
                rules.fall_window_us,
                rules.local_peak_lookback_us,
                rules.aetr_full_scale,
                rules.recovery_followup_us,
                rules.recovery_power_increase_percent,
                rules.recovery_speed_increase_m_s,
            )
        ) or not 0 < rules.endpoint_nearness_fraction < 1 or not (
            0 < rules.partial_reset_fraction < 1
        ) or not (0 <= rules.airspeed_health_probability_min <= 1) or (
            rules.airspeed_excursion_factor <= 1
        ):
            raise ValueError("Invalid stall-test prototype rules")
        return rules


@dataclass(frozen=True, slots=True)
class StallFrame:
    pitch: EvidencePoint
    target: EvidencePoint | None
    roll: EvidencePoint | None
    pilot: EvidencePoint | None
    pilot_deflection_pwm: float | None
    target_nose_up: bool
    pilot_nose_up: bool
    mode: int | None
    armed: bool | None

    @property
    def time_us(self):
        return self.pitch.time_us

    @property
    def nose_up(self):
        return self.mode == 5 and self.armed is True and (
            self.target_nose_up and self.pilot_nose_up
        )

    @property
    def demand_up(self):
        return self.target_nose_up and self.pilot_nose_up


@dataclass(frozen=True, slots=True)
class StallAttempt:
    start_us: int
    confirmed_us: int | None
    end_us: int
    end_reason: StallReason
    complete: bool
    frames: tuple[StallFrame, ...]
    preliminary_reasons: tuple[StallReason, ...] = ()


@dataclass(frozen=True, slots=True)
class StallAttemptContext:
    mode: str
    reference_us: int | None
    throttle_class: str
    median_commanded_throttle_percent: float | None
    bank_class: str
    abs_roll_at_reference_deg: float | None
    flap_command: float | None
    clean_idle_context: bool


@dataclass(frozen=True, slots=True)
class StallDepartureEvent:
    """Logged command/response evidence, not an aerodynamic onset."""

    pitch_peak: EvidencePoint
    first_opposed_fall: EvidencePoint
    confirmed_at: EvidencePoint
    aetr_endpoint: EvidencePoint
    rcou_endpoint: EvidencePoint
    elevator_channel: int
    pitch_fall_deg: float
    error_growth_deg: float
    maximum_association_gap_us: int


@dataclass(frozen=True, slots=True)
class StallResponseEvidence:
    """A provisional opposed response, retained even if endpoints are absent."""

    pitch_peak: EvidencePoint
    first_opposed_fall: EvidencePoint
    confirmed_at: EvidencePoint
    target_at_peak: EvidencePoint
    target_at_confirmation: EvidencePoint
    pilot_at_peak: EvidencePoint
    pilot_at_confirmation: EvidencePoint
    pitch_fall_deg: float
    error_growth_deg: float
    peak_pilot_association_gap_us: int
    confirmation_pilot_association_gap_us: int


class AirspeedQuality(str, Enum):
    USABLE = "usable"
    SUSPECT = "suspect"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SavedAirspeedParameters:
    """Saved PARM state at a named reference, not in-memory calibration."""

    reference_us: int
    values: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class AirspeedMeasurement:
    """One native ARSP sample associated with a named event reference."""

    reference_us: int
    sample: EvidencePoint | None
    association_gap_us: int | None
    sensor_instance: int | None
    primary_instance: int | None
    quality: AirspeedQuality
    warnings: tuple[str, ...]
    corrected_diff_pressure: EvidencePoint | None = None
    logged_offset: EvidencePoint | None = None
    health: EvidencePoint | None = None
    in_use: EvidencePoint | None = None
    health_probability: EvidencePoint | None = None
    consistency_ratio: EvidencePoint | None = None
    saved_parameters: SavedAirspeedParameters | None = None
    saved_parameters_at_sample: SavedAirspeedParameters | None = None
    effective_ratio: float | None = None
    effective_ratio_formula: str | None = None


@dataclass(frozen=True, slots=True)
class StallAirspeedEvidence:
    raw_airspeed_at_pre_fall_pitch_peak: AirspeedMeasurement | None
    raw_airspeed_at_first_opposed_fall_observation: AirspeedMeasurement | None
    lowest_usable_raw_airspeed_in_attempt: AirspeedMeasurement | None
    raw_airspeed_at_recovery_start: AirspeedMeasurement | None
    raw_airspeed_at_observed_recovery_milestone: AirspeedMeasurement | None
    selected_ctun_airspeed_at_peak: EvidencePoint | None = None
    selected_ctun_source_at_peak: EvidencePoint | None = None


@dataclass(frozen=True, slots=True)
class StallRecovery:
    """Independent observed milestones; none implies a completed recovery."""

    control_start: EvidencePoint
    pilot_demand_reduction: EvidencePoint | None
    target_reduction: EvidencePoint | None
    commanded_power_increase: EvidencePoint | None
    pitch_minimum: EvidencePoint | None
    target_at_pitch_minimum: EvidencePoint | None
    pitch_limit_min_deg: float | None
    attitude_below_target_limit: bool | None
    nose_up_elevator_command: EvidencePoint | None
    nose_up_elevator_pwm_command: EvidencePoint | None
    first_sustained_airspeed_increase: EvidencePoint | None
    sink_arrest: EvidencePoint | None
    altitude_at_departure_reference: EvidencePoint | None
    altitude_at_recovery_start: EvidencePoint | None
    lowest_altitude_after_departure: EvidencePoint | None
    altitude_loss_from_departure_reference_m: float | None
    altitude_loss_from_recovery_start_m: float | None
    stabilization: EvidencePoint | None = None


@dataclass(frozen=True, slots=True)
class StallAttemptResult:
    attempt: StallAttempt
    status: StallStatus
    reasons: tuple[StallReason, ...]
    context: StallAttemptContext | None
    response: StallResponseEvidence | None = None
    departure: StallDepartureEvent | None = None
    airspeed: StallAirspeedEvidence | None = None
    recovery: StallRecovery | None = None


@dataclass(frozen=True, slots=True)
class StallFlightResult:
    flight_window: FlightWindow
    results: tuple[StallAttemptResult, ...]
    rule_version: str
    log_file: str | None = None
    firmware_version: str | None = None
