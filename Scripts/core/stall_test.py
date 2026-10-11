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
        )
        if not rules.version or any(
            value <= 0 for value in (
                rules.association_max_us, rules.attitude_max_gap_us,
                rules.airspeed_max_gap_us, rules.minimum_pull_us,
                rules.release_reset_us, rules.partial_reset_us,
                rules.fall_window_us,
                rules.local_peak_lookback_us,
                rules.aetr_full_scale,
            )
        ) or not 0 < rules.endpoint_nearness_fraction < 1 or not (
            0 < rules.partial_reset_fraction < 1
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


@dataclass(frozen=True, slots=True)
class StallAttemptResult:
    attempt: StallAttempt
    status: StallStatus
    reasons: tuple[StallReason, ...]
    context: StallAttemptContext | None
    response: StallResponseEvidence | None = None
    departure: StallDepartureEvent | None = None


@dataclass(frozen=True, slots=True)
class StallFlightResult:
    flight_window: FlightWindow
    results: tuple[StallAttemptResult, ...]
    rule_version: str
