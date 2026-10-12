"""Portable native-row provenance and recovery contracts for stall results."""

import pandas as pd
import pytest

from core.config import Config
from core.params import ParameterChange, ParameterHistory
from core.stall_characterization import StallCharacterizer
from core.stall_test import AirspeedQuality, StallRules, StallStatus
from test_stall_test import _analyse, _log, _one


def _matched(log, **parameters):
    log.messages["VER"] = pd.DataFrame([{
        "TimeUS": 0, "_SourceOrder": 0, "Maj": 4, "Min": 7,
        "Pat": 0, "FWS": "ArduPlane V4.7.0 (1511f271)",
    }])
    settings = {
        "ARSPD_RATIO": 2.65, "ARSPD_OFFSET": -2.9,
        "ARSPD_AUTOCAL": 0, "ARSPD_TYPE": 9, "ARSPD_USE": 1,
        "ARSPD_PRIMARY": 0, "ARSPD_TUBE_ORDR": 2,
        "ARSPD_OPTIONS": 11, "AIRSPEED_STALL": 7.5,
        "AIRSPEED_MIN": 9,
    }
    settings.update(parameters)
    log.parameter_history = ParameterHistory({
        **log.parameter_history.initial_values, **settings,
    })
    log.messages["ARSP"]["Offset"] = -2.9
    return log


def _characterizer(log):
    return StallCharacterizer(log, StallRules.from_config(
        Config("Config/stall_test.yaml"),
    ))


def test_named_event_speeds_are_distinct_native_rows_and_minimum():
    log, window = _log()
    result = _one(_matched(log), window)
    air = result.airspeed
    peak = air.raw_airspeed_at_pre_fall_pitch_peak
    fall = air.raw_airspeed_at_first_opposed_fall_observation
    low = air.lowest_usable_raw_airspeed_in_attempt
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert peak.reference_us == result.departure.pitch_peak.time_us
    assert fall.reference_us == result.departure.first_opposed_fall.time_us
    assert peak.sample.time_us != fall.sample.time_us
    assert peak.sample.value > fall.sample.value > low.sample.value
    assert peak.association_gap_us == abs(peak.sample.time_us - peak.reference_us)
    assert peak.association_gap_us > 0
    assert low.reference_us == low.sample.time_us
    assert peak.quality is AirspeedQuality.USABLE


def test_flight_result_retains_log_and_firmware_identity():
    log, window = _log()
    result = _analyse(_matched(log), window)
    assert result.log_file == "synthetic.bin"
    assert result.firmware_version == "ArduPlane V4.7.0 (1511f271)"


def test_large_association_gap_is_unavailable_without_interpolation():
    log, window = _log()
    _matched(log)
    original = _one(log, window)
    peak_us = original.departure.pitch_peak.time_us
    log.messages["ARSP"] = log.messages["ARSP"].loc[
        ~log.messages["ARSP"]["TimeUS"].between(
            peak_us - 300_000, peak_us + 300_000,
        )
    ]
    peak = _characterizer(log).airspeed(original, None).raw_airspeed_at_pre_fall_pitch_peak
    assert peak.sample is None
    assert peak.quality is AirspeedQuality.UNAVAILABLE
    assert peak.association_gap_us is None
    assert peak.saved_parameters.values["ARSPD_RATIO"] == 2.65


def test_selected_ctun_speed_is_separate_context_not_raw_calibration():
    log, window = _log()
    _matched(log)
    log.messages["CTUN"] = pd.DataFrame([{
        "TimeUS": 1_700_000, "_SourceOrder": 500,
        "As": 20.0, "AsT": 1,
    }])
    air = _one(log, window).airspeed
    assert air.selected_ctun_airspeed_at_peak.source == "CTUN"
    assert air.selected_ctun_source_at_peak.value == 1
    assert air.selected_ctun_airspeed_at_peak.value == 20
    assert air.raw_airspeed_at_pre_fall_pitch_peak.sample.value != 20


def test_primary_sensor_is_chosen_over_closer_secondary_row():
    log, window = _log()
    _matched(log)
    reference = _one(log, window).departure.pitch_peak.time_us
    secondary = pd.DataFrame([{
        "TimeUS": reference, "_SourceOrder": 10_000,
        "Airspeed": 1.0, "DiffPress": 0.5,
        "I": 1, "Pri": 0, "H": 1, "U": 1,
    }])
    log.messages["ARSP"] = pd.concat(
        [log.messages["ARSP"], secondary], ignore_index=True,
    )
    selected = _characterizer(log)._measurement(reference)
    assert selected.sensor_instance == 0
    assert selected.quality is AirspeedQuality.USABLE
    assert selected.sample.value != 1.0


@pytest.mark.parametrize("field,value,reason", [
    ("H", 0, "healthy"),
    ("U", 0, "use"),
    ("DiffPress", float("nan"), "pressure"),
    ("DiffPress", 0, "pressure"),
    ("I", 1, "instance"),
])
def test_suspect_row_is_not_an_attempt_minimum(field, value, reason):
    log, window = _log()
    _matched(log)
    index = log.messages["ARSP"].index[-5]
    sample_us = int(log.messages["ARSP"].loc[index, "TimeUS"])
    log.messages["ARSP"].loc[index, "Airspeed"] = 0.1
    log.messages["ARSP"].loc[index, field] = value
    characterization = _characterizer(log)
    source_row = next(row for row in characterization._source("ARSP")
                      if row.time_us == sample_us)
    selected = characterization._measurement(sample_us, source_row)
    result = _one(log, window)
    assert selected.quality is AirspeedQuality.SUSPECT
    assert any(reason in warning for warning in selected.warnings)
    assert selected.effective_ratio is None
    assert result.airspeed.lowest_usable_raw_airspeed_in_attempt.sample.time_us != sample_us


def test_isolated_healthy_flagged_dropout_does_not_become_minimum():
    log, window = _log()
    _matched(log)
    index = log.messages["ARSP"].index[-5]
    sample_us = int(log.messages["ARSP"].loc[index, "TimeUS"])
    log.messages["ARSP"].loc[index, "Airspeed"] = 0.1
    log.messages["ARSP"].loc[index, "DiffPress"] = 0.01
    result = _one(log, window)
    assert result.airspeed.lowest_usable_raw_airspeed_in_attempt.sample.time_us != sample_us
    assert "isolated abrupt" in _characterizer(log)._measurement(sample_us).warnings[0]


def test_saved_ratio_autocal_offset_and_runtime_ratio_remain_separate():
    log, window = _log()
    _matched(log, ARSPD_AUTOCAL=1)
    log.parameter_history = ParameterHistory(
        log.parameter_history.initial_values,
        {"ARSPD_AUTOCAL": (ParameterChange(1_000_000, 0),),
         "ARSPD_RATIO": (ParameterChange(1_000_000, 2.65),),
         "ARSPD_OFFSET": (ParameterChange(1_000_000, -2.9),)},
    )
    result = _one(log, window)
    peak = result.airspeed.raw_airspeed_at_pre_fall_pitch_peak
    assert peak.saved_parameters.values["ARSPD_AUTOCAL"] == 0
    assert peak.saved_parameters.values["ARSPD_OFFSET"] == -2.9
    assert peak.saved_parameters.values["ARSPD_RATIO"] == 2.65
    assert peak.logged_offset.value == -2.9
    assert peak.effective_ratio == pytest.approx(2.0)
    assert "Airspeed**2 / ARSP.DiffPress" in peak.effective_ratio_formula
    assert peak.effective_ratio != peak.saved_parameters.values["ARSPD_RATIO"]
    before = _characterizer(log)._saved(500_000)
    assert before.values["ARSPD_AUTOCAL"] == 1


def test_parameter_change_between_event_and_arsp_row_keeps_both_times():
    log, window = _log()
    _matched(log)
    reference = _one(log, window).departure.pitch_peak.time_us
    sampled = _characterizer(log)._measurement(reference).sample.time_us
    assert reference < sampled
    change_us = (reference + sampled) // 2
    log.parameter_history = ParameterHistory(
        log.parameter_history.initial_values,
        {"ARSPD_RATIO": (ParameterChange(change_us, 3.0),)},
    )
    air = _characterizer(log)._measurement(reference)
    assert air.saved_parameters.reference_us == reference
    assert air.saved_parameters.values["ARSPD_RATIO"] == 2.65
    assert air.saved_parameters_at_sample.reference_us == sampled
    assert air.saved_parameters_at_sample.values["ARSPD_RATIO"] == 3.0
    assert air.effective_ratio == pytest.approx(2.0)


def test_unsupported_firmware_or_sensor_setting_never_falls_back_to_saved_ratio():
    log, window = _log()
    _matched(log)
    reference = _one(log, window).departure.pitch_peak.time_us
    log.messages["VER"].loc[0, "FWS"] = "ArduPlane V4.7.1 (different)"
    unsupported = _characterizer(log)._measurement(reference)
    assert unsupported.quality is AirspeedQuality.USABLE
    assert unsupported.effective_ratio is None
    assert "unsupported" in unsupported.warnings[0]
    log.messages["VER"].loc[0, "FWS"] = "ArduPlane V4.7.0 (1511f271)"
    log.parameter_history = ParameterHistory({
        **log.parameter_history.initial_values, "ARSPD_TUBE_ORDR": 1,
    })
    assert _characterizer(log)._measurement(reference).effective_ratio is None


def test_recovery_milestones_are_independent_and_altitude_loss_is_named():
    log, window = _log()
    _matched(log, PTCH_LIM_MIN_DEG=-10)
    att = log.messages["ATT"]
    att.loc[att["TimeUS"] >= 3_300_000, "Pitch"] = -15
    att.loc[att["TimeUS"] >= 3_300_000, "DesPitch"] = -8
    speeds = log.messages["ARSP"]
    mask = speeds["TimeUS"] >= 3_140_000
    speeds.loc[mask, "Airspeed"] = 13 + (
        speeds.loc[mask, "TimeUS"] - 3_140_000
    ) / 300_000
    speeds.loc[mask, "DiffPress"] = speeds.loc[mask, "Airspeed"] ** 2 / 2
    log.messages["AETR"].loc[
        log.messages["AETR"]["TimeUS"] >= 3_300_000, "Elev",
    ] = 2000
    log.messages["RCOU"].loc[
        log.messages["RCOU"]["TimeUS"] >= 3_300_000, "C2",
    ] = 1700
    log.messages["BARO"] = pd.DataFrame([
        {"TimeUS": t, "_SourceOrder": 1000 + i, "Alt": altitude, "CRt": rate}
        for i, (t, altitude, rate) in enumerate([
            (1_700_000, 100, -1), (3_000_000, 95, -3),
            (3_200_000, 94, -2), (3_400_000, 92, -1),
            (3_600_000, 90, -0.5), (3_800_000, 91, 0.2),
        ])
    ])
    result = _one(log, window)
    recovery = result.recovery
    assert recovery.pilot_demand_reduction is not None
    assert recovery.control_start.time_us <= recovery.pitch_minimum.time_us
    assert recovery.first_sustained_airspeed_increase is not None
    assert recovery.first_sustained_airspeed_increase.time_us > recovery.control_start.time_us
    assert recovery.pitch_minimum.value == -15
    assert recovery.pitch_limit_min_deg == -10
    assert recovery.attitude_below_target_limit is True
    assert recovery.target_at_pitch_minimum.value == -8
    assert recovery.nose_up_elevator_command.value > 0
    assert recovery.nose_up_elevator_pwm_command.value > 1500
    assert recovery.altitude_at_departure_reference.value == 100
    assert recovery.lowest_altitude_after_departure.value == 90
    assert recovery.altitude_loss_from_departure_reference_m == 10
    assert recovery.altitude_loss_from_recovery_start_m is not None
    assert recovery.sink_arrest.time_us == 3_800_000
    assert recovery.stabilization is None


def test_incomplete_departure_does_not_invent_recovery_at_log_boundary():
    log, window = _log(pulls=((0.2, 4.0),), end=4.0)
    speed = log.messages["ARSP"]
    mask = speed["TimeUS"] >= 3_140_000
    speed.loc[mask, "Airspeed"] += 2
    speed.loc[mask, "DiffPress"] = speed.loc[mask, "Airspeed"] ** 2 / 2
    result = _one(_matched(log), window)
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert result.attempt.complete is False
    assert result.recovery is None
    assert result.airspeed.raw_airspeed_at_recovery_start is None


def test_release_without_later_speed_rise_has_partial_recovery():
    log, window = _log(speed="flat")
    # Restore a decelerating entry so that the existing classifier sees an attempt.
    speeds = log.messages["ARSP"]
    speeds.loc[speeds["TimeUS"] <= 3_040_000, "Airspeed"] = (
        15 - 0.8 * speeds.loc[speeds["TimeUS"] <= 3_040_000, "TimeUS"] / 1e6
    )
    speeds["DiffPress"] = speeds["Airspeed"] ** 2 / 2
    result = _one(_matched(log), window)
    assert result.status is StallStatus.PROBABLE_DEPARTURE
    assert result.recovery is not None
    assert result.recovery.first_sustained_airspeed_increase is None
    assert result.airspeed.raw_airspeed_at_observed_recovery_milestone is None
