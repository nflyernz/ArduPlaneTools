"""Portable contracts for the FBWA stall-test prototype core."""

import pandas as pd
import pytest

from core.config import Config
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.params import ParameterChange, ParameterHistory
from core.stall_departure_detector import StallTestAnalyzer
from core.stall_test import StallReason, StallStatus


def _log(*, profile="break", pulls=((0.2, 3.0),), end=4.0,
         endpoint=True, speed="healthy", channel=2, reversed_output=False,
         throttle=0.0, roll=0.0, skew=0.0):
    """Native, offset streams; no private BIN or interpolated common rows."""
    events = [
        ("MODE", 0, {"Mode": 5, "ModeNum": 5}),
        ("ARM", 0, {"ArmState": 1}),
        ("STAT", 0, {"Armed": 1}),
    ]
    for n in range(1, round(end * 10) + 1):
        t = n / 10
        current = next(((start, stop) for start, stop in pulls
                        if start <= t <= stop), None)
        up = current is not None
        local = t - current[0] if current else None
        if profile == "release" and t >= 2.0:
            up = False
        if profile == "steady":
            pitch = 5.0
        elif profile == "weak":
            pitch = (6 + 2 * min(t, 1.9) if t <= 1.9
                     else 9.8 - 4 * (t - 1.9))
        elif profile == "release":
            pitch = 6 + 2 * min(t, 2.1) if t <= 2.1 else 10.2 - 12 * (t - 2.1)
        elif profile == "double" and local is not None and local > 2.5:
            pitch = (2 + 12 * (local - 2.5) if local <= 3.0
                     else 8 - 12 * (local - 3.0))
        else:
            phase = local if local is not None else t
            pitch = (6 + 2 * min(phase, 1.7) if phase <= 1.7
                     else 9.4 - 12 * (phase - 1.7))
        rc_time = round((t - 0.03) * 1_000_000)
        att_time = round(t * 1_000_000)
        aetr_time = round((t + 0.01) * 1_000_000)
        rcou_time = round((t + 0.02 + skew) * 1_000_000)
        speed_time = round((t + 0.04) * 1_000_000)
        endpoint_now = endpoint and up and local is not None and (
            2.0 <= local <= 2.6
        )
        events.extend([
            ("RCIN", rc_time, {"C2": 1700 if up else 1500}),
            ("ATT", att_time, {
                "Pitch": pitch, "DesPitch": 15.0 if up else 0.0,
                "Roll": roll, "DesRoll": 0.0,
            }),
            ("AETR", aetr_time, {
                "Elev": 4500 if endpoint_now else 2000,
                "Thr": throttle, "Flap": 0,
            }),
            ("RCOU", rcou_time, {
                f"C{channel}": (
                    1100 if reversed_output else 1900
                ) if endpoint_now else 1500,
            }),
        ])
        if speed != "missing":
            velocity = 15.0 if speed == "flat" else 15.0 - 0.8 * t
            events.append(("ARSP", speed_time, {
                "Airspeed": velocity, "DiffPress": velocity**2 / 2,
                "I": 0, "Pri": 0, "H": 0 if speed == "unhealthy" else 1,
                "U": 1,
            }))
    records = {}
    for order, (source, time_us, values) in enumerate(
        sorted(events, key=lambda event: event[1])
    ):
        records.setdefault(source, []).append({
            "TimeUS": time_us, "_SourceOrder": order, **values,
        })
    parameters = {
        "RCMAP_PITCH": 2, "RC2_TRIM": 1500, "RC2_REVERSED": 0,
        f"SERVO{channel}_FUNCTION": 19,
        f"SERVO{channel}_MIN": 1100,
        f"SERVO{channel}_MAX": 1900,
        f"SERVO{channel}_REVERSED": int(reversed_output),
    }
    window = FlightWindow(0, round(end * 1_000_000))
    return FlightLog(
        messages={name: pd.DataFrame(values)
                  for name, values in records.items()},
        parameter_history=ParameterHistory(parameters),
        flights=[window],
        metadata={"log_file": "synthetic.bin"},
    ), window


def _analyse(log, window):
    return StallTestAnalyzer(Config("Config/stall_test.yaml")).analyse(log, window)


def _one(log, window):
    result = _analyse(log, window)
    assert result.rule_version == "fbwa-prototype-1"
    assert len(result.results) == 1
    return result.results[0]


def test_ordered_fbwa_response_and_mapped_endpoint_are_probable():
    result = _one(*_log())
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert result.attempt.confirmed_us > result.attempt.start_us
    assert result.attempt.complete
    assert result.departure.elevator_channel == 2
    assert (result.departure.pitch_peak.time_us
            < result.departure.first_opposed_fall.time_us
            < result.departure.confirmed_at.time_us)
    assert result.departure.pitch_fall_deg >= 6
    assert result.departure.error_growth_deg >= 3
    assert result.departure.aetr_endpoint.source == "AETR"
    assert result.departure.rcou_endpoint.source == "RCOU"
    assert result.departure.maximum_association_gap_us <= 200_000
    assert result.response.pilot_at_peak.source == "RCIN"
    assert result.response.target_at_confirmation.source == "ATT"
    assert result.response.peak_pilot_association_gap_us <= 200_000
    assert result.context.clean_idle_context


@pytest.mark.parametrize("profile", ["release", "steady"])
def test_no_break_or_fall_after_release_is_analyzed_negative(profile):
    result = _one(*_log(profile=profile, endpoint=False))
    assert result.status is StallStatus.NO_DEMONSTRATED_DEPARTURE
    assert result.departure is None
    assert StallReason.NO_OPPOSED_FALL in result.reasons


def test_endpoint_without_sustained_fall_is_ambiguous():
    result = _one(*_log(profile="weak"))
    assert result.status is StallStatus.AMBIGUOUS
    assert StallReason.ENDPOINT_WITHOUT_FALL in result.reasons


def test_large_pitch_error_with_no_fall_is_not_positive():
    result = _one(*_log(profile="steady", endpoint=False))
    assert result.status is StallStatus.NO_DEMONSTRATED_DEPARTURE


def test_roll_and_sink_cannot_substitute_for_opposed_pitch_fall():
    log, window = _log(profile="steady", endpoint=False, roll=30)
    log.messages["BARO"] = pd.DataFrame([{
        "TimeUS": 2_500_000, "Alt": 10.0, "CRt": -5.0,
        "_SourceOrder": 10000,
    }])
    log.messages["IMU"] = pd.DataFrame([{
        "TimeUS": 2_500_000, "GyrX": 1.0, "GyrY": -1.0,
        "_SourceOrder": 10001,
    }])
    result = _one(log, window)
    assert result.status is StallStatus.NO_DEMONSTRATED_DEPARTURE
    assert result.context.bank_class == "banked"
    assert not result.context.clean_idle_context


def test_no_break_bank_context_uses_low_speed_reference():
    log, window = _log(profile="release", endpoint=False, throttle=50)
    att = log.messages["ATT"]
    att.loc[att["TimeUS"].between(1_800_000, 2_200_000), "Roll"] = 35
    result = _one(log, window)
    assert result.status is StallStatus.NO_DEMONSTRATED_DEPARTURE
    assert result.context.bank_class == "banked"
    assert result.context.reference_us is not None
    assert not result.context.clean_idle_context


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("mapping", StallReason.MISSING_ELEVATOR_MAPPING),
        ("command", StallReason.MISSING_COMMAND_ENDPOINT),
        ("output", StallReason.MISSING_OUTPUT_ENDPOINT),
    ],
)
def test_missing_mapped_endpoint_preserves_response_as_ambiguous(change, reason):
    log, window = _log()
    if change == "mapping":
        log.parameter_history = ParameterHistory({
            "RCMAP_PITCH": 2, "RC2_TRIM": 1500,
        })
    elif change == "command":
        log.messages["AETR"]["Elev"] = 2000
    else:
        log.messages["RCOU"]["C2"] = 1500
    result = _one(log, window)
    assert result.status is StallStatus.AMBIGUOUS
    assert result.response is not None
    assert result.departure is None
    assert reason in result.reasons


@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        ("missing", StallReason.MISSING_AIRSPEED),
        ("unhealthy", StallReason.UNHEALTHY_AIRSPEED),
    ],
)
def test_missing_or_unhealthy_air_data_is_ambiguous(condition, reason):
    result = _one(*_log(speed=condition))
    assert result.status is StallStatus.AMBIGUOUS
    assert reason in result.reasons


def test_relative_speed_drop_is_eligibility_not_departure_trigger():
    result = _one(*_log(profile="steady", speed="flat", endpoint=False))
    assert result.status is StallStatus.REJECTED
    assert StallReason.NO_SLOW_FLIGHT in result.reasons


def test_brief_movement_is_rejected_candidate():
    result = _one(*_log(pulls=((0.2, 0.5),), endpoint=False))
    assert result.status is StallStatus.REJECTED
    assert StallReason.SHORT_MOVEMENT in result.reasons


def test_missing_fbwa_target_or_rc_stream_is_rejected_diagnostic():
    log, window = _log()
    log.messages["ATT"]["DesPitch"] = float("nan")
    result = _one(log, window)
    assert result.status is StallStatus.REJECTED
    assert StallReason.MISSING_TARGET in result.reasons


def test_missing_pilot_stream_is_rejected_diagnostic():
    log, window = _log()
    del log.messages["RCIN"]
    result = _one(log, window)
    assert result.status is StallStatus.REJECTED
    assert StallReason.MISSING_PITCH_INPUT in result.reasons


def test_disarmed_fbwa_ground_pull_is_rejected():
    log, window = _log()
    log.messages["ARM"]["ArmState"] = 0
    log.messages["STAT"]["Armed"] = 0
    result = _one(log, window)
    assert result.status is StallStatus.REJECTED
    assert StallReason.NOT_ARMED in result.reasons


def test_wrong_mode_pull_is_visible_rejected_candidate():
    log, window = _log()
    log.messages["MODE"]["Mode"] = 0
    log.messages["MODE"]["ModeNum"] = 0
    result = _one(log, window)
    assert result.status is StallStatus.REJECTED
    assert StallReason.NOT_FBWA in result.reasons
    assert result.context.mode == "MANUAL"


def test_conflicting_arm_and_stat_is_rejected_with_explicit_reason():
    log, window = _log()
    log.messages["STAT"]["Armed"] = 0
    result = _one(log, window)
    assert result.status is StallStatus.REJECTED
    assert StallReason.UNKNOWN_ARMED_STATE in result.reasons


def test_compound_falls_remain_one_attempt():
    result = _one(*_log(profile="double", pulls=((0.2, 4.2),), end=5.0))
    assert result.status is StallStatus.PROBABLE_DEPARTURE


def test_release_and_reapply_make_two_attempts():
    log, window = _log(pulls=((0.2, 3.0), (4.0, 6.8)), end=7.8)
    result = _analyse(log, window)
    assert len(result.results) == 2
    assert all(item.status is StallStatus.PROBABLE_DEPARTURE
               for item in result.results)
    assert result.results[0].attempt.end_us < result.results[1].attempt.start_us


def test_substantial_partial_release_then_reapplication_splits_pull():
    log, window = _log(pulls=((0.2, 6.8),), end=7.8)
    rcin = log.messages["RCIN"]
    att = log.messages["ATT"]
    rcin.loc[rcin["TimeUS"].between(3_270_000, 3_570_000), "C2"] = 1550
    att.loc[att["TimeUS"].between(3_300_000, 3_600_000), "DesPitch"] = 4
    result = _analyse(log, window)
    assert len(result.results) == 2
    assert result.results[0].attempt.end_us < result.results[1].attempt.start_us


def test_complete_evidence_before_log_boundary_remains_probable():
    result = _one(*_log(pulls=((0.2, 4.0),), end=2.9))
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert not result.attempt.complete
    assert result.attempt.end_reason is StallReason.FLIGHT_BOUNDARY


def test_mode_change_during_crucial_fall_keeps_ambiguous_attempt():
    log, window = _log()
    log.messages["MODE"] = pd.concat([
        log.messages["MODE"], pd.DataFrame([{
            "TimeUS": 2_200_000, "_SourceOrder": 10000,
            "Mode": 10, "ModeNum": 10,
        }]),
    ], ignore_index=True)
    results = _analyse(log, window).results
    assert results[0].status is StallStatus.AMBIGUOUS
    assert results[0].attempt.end_reason is StallReason.MODE_BOUNDARY
    assert results[1].status is StallStatus.REJECTED
    assert StallReason.NOT_FBWA in results[1].reasons


def test_reversed_elevator_on_different_channel_maps_to_minimum():
    result = _one(*_log(channel=4, reversed_output=True, throttle=55, roll=25))
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert result.departure.elevator_channel == 4
    assert result.departure.rcou_endpoint.field == "C4"
    assert result.departure.rcou_endpoint.value == 1100
    assert not result.context.clean_idle_context


def test_servo_function_change_at_event_time_blocks_stale_mapping():
    log, window = _log()
    initial = dict(log.parameter_history.initial_values)
    initial["SERVO4_FUNCTION"] = 0
    initial["SERVO4_MIN"] = 1100
    initial["SERVO4_MAX"] = 1900
    initial["SERVO4_REVERSED"] = 0
    log.parameter_history = ParameterHistory(initial, {
        "SERVO2_FUNCTION": (ParameterChange(2_100_000, 0),),
        "SERVO4_FUNCTION": (ParameterChange(2_100_000, 19),),
    })
    result = _one(log, window)
    assert result.status is StallStatus.AMBIGUOUS
    assert result.departure is None


def test_attitude_gap_cannot_be_filled_by_interpolation():
    log, window = _log()
    att = log.messages["ATT"]
    log.messages["ATT"] = att[~att["TimeUS"].between(
        1_950_000, 2_550_000,
    )].copy()
    result = _analyse(log, window)
    assert all(item.status is not StallStatus.PROBABLE_DEPARTURE
               for item in result.results)
    assert any(StallReason.EVIDENCE_GAP in item.reasons
               for item in result.results)


def test_cross_stream_skew_within_bound_keeps_native_times():
    result = _one(*_log(skew=0.10))
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert result.departure.aetr_endpoint.time_us != (
        result.departure.rcou_endpoint.time_us
    )
    assert result.departure.maximum_association_gap_us <= 200_000


def test_unbounded_endpoint_association_cannot_produce_probable_event():
    log, window = _log()
    aetr = log.messages["AETR"]
    rcou = log.messages["RCOU"]
    aetr.loc[aetr["TimeUS"] != 2_310_000, "Elev"] = 2000
    rcou.loc[rcou["TimeUS"] != 2_720_000, "C2"] = 1500
    result = _one(log, window)
    assert result.status is StallStatus.AMBIGUOUS
    assert result.response is not None
    assert result.departure is None
