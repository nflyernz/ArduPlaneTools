"""Portable BAT evidence tests for the read-only load response."""

import os
from pathlib import Path

import pandas as pd
import pytest

from analyses.battery import format_battery_report
from core.battery import BatteryLoadEventType, BatteryProcessor
from core.battery_load_response import detect_auto_load_onset, evaluate_load_response
from core.config import Config
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.log_reader import FlightReader
from core.params import ParameterHistory
from test_support import require_log


def _bat(
    *, reduction_s=5.0, spike=False, reaccelerate=False, baseline=True, last_s=26.0
):
    rows = []
    for tick in range(int(last_s * 10) + 1):
        seconds = tick / 10
        current = 2.0 if seconds < 1 and baseline else 20.0
        if seconds >= reduction_s:
            current = 10.0
        if spike and seconds == 2:
            current = 50.0
        if reaccelerate and seconds >= 12:
            current = 22.0
        rows.append(
            {
                "TimeUS": tick * 100_000,
                "Inst": 0,
                "Volt": 16.0 if seconds < 1 else 14.0,
                "Curr": current,
            }
        )
    return pd.DataFrame(rows)


def test_confirmed_reduction_uses_actual_beginning_and_raw_peak():
    response = evaluate_load_response(_bat(spike=True), 0, 1_000_000, 26_000_000)
    assert response.t1_us == 5_200_000  # trailing median, then 3 s confirmation
    assert response.reference_current_a == 20.0
    assert response.raw_peak_current_a == 50.0
    assert response.baseline_voltage_v == 16.0
    assert response.baseline_current_a == 2.0
    assert response.minimum_voltage_v == 14.0
    assert response.current_at_minimum_a == 20.0
    assert response.voltage_drop_v == 2.0
    assert response.follow_up_voltage_v == 14.0
    assert response.follow_up_current_a == 10.0


def test_twenty_second_fallback_is_observation_not_load_end():
    response = evaluate_load_response(_bat(reduction_s=30), 0, 1_000_000, 26_000_000)
    assert response.t1_us is None
    assert response.observation_end_us == 21_000_000
    assert "20-second observation window" in response.status
    assert "Confirmed" not in response.status


def test_late_reduction_cannot_confirm_beyond_horizon():
    response = evaluate_load_response(_bat(reduction_s=19), 0, 1_000_000, 26_000_000)
    assert response.t1_us is None
    assert response.observation_end_us == 21_000_000


def test_reacceleration_is_explicit_not_final_load_end():
    response = evaluate_load_response(_bat(reaccelerate=True), 0, 1_000_000, 26_000_000)
    assert response.t1_us is not None
    assert response.reaccelerated
    assert "not final load end" in response.status


def test_missing_baseline_and_truncation_are_reported():
    response = evaluate_load_response(
        _bat(reduction_s=30, baseline=False, last_s=12), 0, 1_000_000, 12_000_000
    )
    assert response.baseline_voltage_v is None
    assert response.voltage_drop_v is None
    assert response.t1_us is None
    assert "truncated" in response.status
    assert "baseline unavailable" in response.status


def test_isolated_low_current_dips_do_not_create_baseline_or_voltage_drop():
    bat = _bat(baseline=False)
    for tick in (1, 5, 9):
        bat.loc[tick, ["Curr", "Volt"]] = [2.0, 16.0]
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.t1_us is not None
    assert response.baseline_voltage_v is None
    assert response.baseline_current_a is None
    assert response.voltage_drop_v is None
    assert "baseline unavailable" in response.status


def test_stepped_low_current_baseline_is_rejected_without_losing_t1():
    bat = _bat(baseline=False)
    bat.loc[:5, ["Curr", "Volt"]] = [1.0, 16.0]
    bat.loc[6:9, ["Curr", "Volt"]] = [5.0, 15.6]
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.reference_current_a == 20.0
    assert response.t1_us == 5_200_000
    assert response.raw_peak_current_a == 20.0
    assert response.minimum_voltage_v == 14.0
    assert response.baseline_voltage_v is None
    assert response.baseline_current_a is None
    assert response.voltage_drop_v is None


def test_recent_stable_baseline_survives_earlier_transient():
    bat = _bat(reduction_s=10, baseline=False)
    bat.loc[:5, ["Curr", "Volt"]] = [5.0, 15.6]
    bat.loc[6:19, ["Curr", "Volt"]] = [1.0, 16.0]
    response = evaluate_load_response(bat, 0, 2_000_000, 26_000_000)
    assert response.baseline_voltage_v == 16.0
    assert response.baseline_current_a == 1.0
    assert response.voltage_drop_v == 2.0


def test_late_transition_blocks_earlier_stable_baseline():
    bat = _bat(baseline=False)
    bat.loc[:7, ["Curr", "Volt"]] = [1.0, 16.0]
    bat.loc[8:9, ["Curr", "Volt"]] = [5.0, 15.6]
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.baseline_voltage_v is None
    assert response.baseline_current_a is None
    assert response.voltage_drop_v is None


def test_ordinary_low_current_and_voltage_noise_keeps_baseline():
    bat = _bat()
    for tick in range(10):
        bat.loc[tick, "Curr"] = 2.0 + (0.04 if tick % 2 else -0.04)
        bat.loc[tick, "Volt"] = 16.0 + (0.02 if tick % 2 else -0.02)
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.baseline_voltage_v == 16.0
    assert response.baseline_current_a == 2.0
    assert response.voltage_drop_v == 2.0


def test_reference_gap_prevents_unconditional_t1_confirmation():
    bat = _bat(reduction_s=10).loc[
        lambda frame: ~frame.TimeUS.between(1_500_000, 3_300_000)
    ]
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.reference_current_a is None
    assert response.t1_us is None
    assert response.raw_peak_current_a == 20.0
    assert response.minimum_voltage_v == 14.0
    assert "Current reference unavailable" in response.status
    assert "Confirmed" not in response.status


def test_confirmation_gap_cannot_bridge_short_low_current_stage():
    bat = _bat(reduction_s=8)
    bat.loc[bat.TimeUS >= 11_000_000, "Curr"] = 20.0
    bat = bat.loc[~bat.TimeUS.between(9_000_000, 9_600_000)]
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.reference_current_a == 20.0
    assert response.t1_us is None
    assert response.gaps


def test_remote_invalid_timestamp_does_not_mask_valid_event():
    bat = _bat()
    bat.loc[len(bat)] = [float("nan"), 0, 14.0, 10.0]
    assert detect_auto_load_onset(bat, 0, 800_000, 1_500_000) == 1_000_000
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.t1_us == 5_200_000


def test_late_follow_up_is_unavailable_with_explicit_reason():
    bat = _bat().loc[lambda frame: ~frame.TimeUS.between(10_200_000, 23_900_000)]
    response = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert response.t1_us == 5_200_000
    assert response.follow_up_time_us is None
    assert response.follow_up_voltage_v is None
    assert "follow-up unavailable within 0.4 s" in response.status


def test_missing_current_and_invalid_timestamp_do_not_establish_response():
    missing = _bat()
    missing["Curr"] = float("nan")
    assert (
        "unavailable"
        in evaluate_load_response(missing, 0, 1_000_000, 26_000_000).status
    )
    invalid = _bat()
    invalid.loc[20, "TimeUS"] = float("nan")
    assert (
        "timestamps incomplete"
        in evaluate_load_response(invalid, 0, 1_000_000, 26_000_000).status
    )


def test_auto_boundary_already_under_load_has_no_invented_onset():
    assert detect_auto_load_onset(_bat(baseline=False), 0, 800_000, 1_500_000) is None
    assert detect_auto_load_onset(_bat(), 0, 800_000, 1_500_000) == 1_000_000


def test_unstable_baseline_and_single_spike_do_not_establish_auto_onset():
    unstable = _bat()
    unstable.loc[:9, "Curr"] = [0.5, 4.5] * 5
    assert detect_auto_load_onset(unstable, 0, 800_000, 1_500_000) is None
    spike = _bat(baseline=False)
    spike.loc[:9, "Curr"] = 2.0
    spike.loc[10, "Curr"] = 50.0
    spike.loc[11:, "Curr"] = 2.0
    assert detect_auto_load_onset(spike, 0, 800_000, 1_500_000) is None


def test_repeated_preboundary_bursts_and_inadequate_baseline_are_ambiguous():
    bursts = _bat()
    bursts.loc[bursts.TimeUS.between(1_600_000, 2_500_000), "Curr"] = 2.0
    assert detect_auto_load_onset(bursts, 0, 800_000, 3_000_000) is None
    short = _bat()[lambda frame: frame.TimeUS >= 600_000]
    assert detect_auto_load_onset(short, 0, 800_000, 1_500_000) is None


def test_missing_and_discontinuous_auto_evidence_is_rejected():
    assert detect_auto_load_onset(pd.DataFrame(), 0, 800_000, 1_500_000) is None
    invalid = _bat()
    invalid.loc[9, "TimeUS"] = float("nan")
    assert detect_auto_load_onset(invalid, 0, 800_000, 1_500_000) is None
    gapped = _bat().drop(index=[4, 5, 6, 7])
    assert detect_auto_load_onset(gapped, 0, 800_000, 1_500_000) is None


def test_delayed_peak_and_interrupted_confirmation_use_real_timestamps():
    delayed = _bat(reduction_s=12)
    delayed.loc[delayed.TimeUS.between(8_000_000, 9_000_000), "Curr"] = 25.0
    result = evaluate_load_response(delayed, 0, 1_000_000, 26_000_000)
    assert result.t1_us == 12_200_000
    assert result.reference_current_a == 20.0
    interrupted = _bat(reduction_s=5)
    interrupted.loc[interrupted.TimeUS.between(6_000_000, 7_000_000), "Curr"] = 20.0
    result = evaluate_load_response(interrupted, 0, 1_000_000, 26_000_000)
    assert result.t1_us is not None
    assert result.t1_us > 7_000_000


def test_insufficient_reduction_uses_twenty_second_observation():
    bat = _bat(reduction_s=30)
    bat.loc[bat.TimeUS >= 5_000_000, "Curr"] = 18.0
    result = evaluate_load_response(bat, 0, 1_000_000, 26_000_000)
    assert result.t1_us is None
    assert "20-second observation window" in result.status


def test_confirmed_auto_context_adds_distinct_read_only_report():
    flight = FlightWindow(1_500_000, 25_000_000)
    log = FlightLog(
        messages={
            "BAT": _bat(),
            "MODE": pd.DataFrame(
                [
                    {"TimeUS": 500_000, "ModeNum": 13},
                    {"TimeUS": 7_000_000, "ModeNum": 5},
                ]
            ),
            "MSG": pd.DataFrame(
                [
                    {"TimeUS": 900_000, "Message": "Triggered AUTO"},
                ]
            ),
        },
        parameter_history=ParameterHistory({}),
        flights=[flight],
    )
    analysis = BatteryProcessor(log, flight, 0).analyse()
    assert analysis is not None
    assert analysis.battery_load_response.t0_us == 1_000_000
    assert analysis.battery_load_response.t1_us == 5_200_000
    report = format_battery_report(Path("synthetic.bin"), flight, analysis)
    assert "BATTERY LOAD RESPONSE (read-only, AUTO context)" in report
    assert "Voltage/current at first BAT sample ≥5 s after observation" in report
    assert "not unloaded recovery" in report
    assert "Legacy adjacent-sample voltage drop" in report
    assert "Legacy V/A estimate (not cell resistance)" in report
    assert "Legacy interval voltage drop" in report


def test_ground_run_without_confirmed_auto_takeoff_has_no_response():
    flight = FlightWindow(1_500_000, 25_000_000)
    log = FlightLog(
        messages={"BAT": _bat(), "MODE": pd.DataFrame(), "MSG": pd.DataFrame()},
        parameter_history=ParameterHistory({}),
        flights=[flight],
    )
    analysis = BatteryProcessor(log, flight, 0).analyse()
    assert analysis is not None
    assert analysis.battery_load_response is None


@pytest.mark.parametrize(
    "name,cases",
    [
        (
            "log_61_2026-10-25-10-45-48Pc.bin",
            ((712.10, 715.50), (1080.80, 1089.80), (1360.70, 1364.60)),
        ),
        (
            "log_63_2026-10-25-11-24-56Pc.bin",
            ((163.16, 172.26), (435.36, 437.96), (664.46, 667.96)),
        ),
        ("log_73_2026-11-15-09-27-30Pc.bin", ((437.12, 444.52), (929.52, 935.12))),
        ("log_74_2026-11-15-09-56-12Pc.bin", ((147.71, 155.31),)),
        ("log_3_2026-11-15-10-58-12Rg.bin", ((222.86, 227.76), (603.76, 609.96))),
    ],
)
def test_provisional_five_log_replay(name, cases):
    """Replay manual T0 anchors; this does not validate an onset classifier."""
    directory = Path(os.environ.get("APT_REAL_LOG_DIR", "Logs"))
    path = require_log(directory / name)
    log = FlightReader(path, config=Config("Config/battery.yaml")).read()
    bat = log.get("BAT")
    end_us = int(bat.TimeUS.max())
    for t0_s, expected_t1_s in cases:
        response = evaluate_load_response(bat, 0, round(t0_s * 1_000_000), end_us)
        assert response.t1_us is not None
        assert abs(response.t1_us / 1_000_000 - expected_t1_s) <= 0.2


def test_ranger_auto_onsets_and_load_response():
    """Both trigger-confirmed AUTO flights must retain v1 events and find T0."""
    directory = Path(os.environ.get("APT_REAL_LOG_DIR", "Logs"))
    path = require_log(directory / "log_3_2026-11-15-10-58-12Rg.bin")
    log = FlightReader(path, config=Config("Config/battery.yaml")).read()
    found = []
    for flight in log.flights:
        analysis = BatteryProcessor(log, flight, 0).analyse()
        if analysis is None or not any(
            event.event_type is BatteryLoadEventType.TAKEOFF
            for event in analysis.bounded_load_events
        ):
            continue
        found.append(analysis.battery_load_response)
    assert len(found) == 2
    for response, t0_s, t1_s in zip(found, (222.458, 603.359), (227.759, 609.958)):
        assert response.t0_us is not None
        assert response.t1_us is not None
        assert abs(response.t0_us / 1_000_000 - t0_s) < 0.02
        assert abs(response.t1_us / 1_000_000 - t1_s) < 0.02
        assert response.baseline_voltage_v is not None
