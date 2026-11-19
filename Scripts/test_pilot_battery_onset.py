"""Behavioral regressions for read-only pilot-specific BAT onset evidence."""

import pandas as pd
import pytest
from core.pilot_battery_onset import detect_pilot_load_onset, observe_gps_anchored_bat


def _telemetry(current_at, throttle_at):
    battery = []
    throttle = []
    for tick in range(301):
        second = tick / 10
        current = current_at(second)
        battery.append({"TimeUS": tick * 100_000, "Inst": 0,
                        "Curr": current, "Volt": 16 - 0.05 * current})
        throttle.append({"TimeUS": tick * 100_000, "ThO": throttle_at(second)})
    return pd.DataFrame(battery), pd.DataFrame(throttle)


@pytest.mark.parametrize("start,expected", [(8, 8), (12, 12)])
def test_pilot_power_rise_can_precede_or_follow_gps_acceleration(start, expected):
    bat, ctun = _telemetry(lambda second: 2 if second < start else 20,
                           lambda second: 70 if second >= min(start, 10) else 0)
    onset = detect_pilot_load_onset(bat, 0, 10_000_000, ctun)
    assert onset.t0_us == pytest.approx(expected * 1_000_000, abs=100_000)
    assert onset.baseline_current_a == pytest.approx(2)
    assert onset.confirmed_current_a == pytest.approx(20)


def test_gradual_power_application_has_a_qualified_first_load_stage():
    bat, ctun = _telemetry(
        lambda second: 2 if second < 7 else min(20, 2 + 3 * (second - 7)),
        lambda second: 70 if second >= 7 else 0,
    )
    onset = detect_pilot_load_onset(bat, 0, 10_000_000, ctun)
    assert onset.t0_us is not None
    assert 7_000_000 < onset.t0_us < 10_000_000
    assert onset.confirmed_current_a > onset.onset_threshold_a


def test_taxi_power_is_not_mistaken_for_later_takeoff_power():
    bat, ctun = _telemetry(
        lambda second: 2 if second < 4 else 5 if second < 9 else 20,
        lambda second: 10 if second < 8 else 70,
    )
    onset = detect_pilot_load_onset(bat, 0, 10_000_000, ctun)
    assert onset.t0_us == pytest.approx(9_000_000, abs=100_000)
    assert onset.baseline_current_a == pytest.approx(5)


def test_multistage_rise_selects_sustained_launch_stage_after_taxi():
    bat, ctun = _telemetry(
        lambda second: 2 if second < 7 else 6 if second < 9 else 20,
        lambda second: 70 if second >= 7 else 0,
    )
    onset = detect_pilot_load_onset(bat, 0, 10_000_000, ctun)
    assert onset.t0_us == pytest.approx(9_000_000, abs=100_000)
    assert onset.baseline_current_a == pytest.approx(6)


def test_isolated_bat_spike_and_missing_baseline_leave_t0_unavailable():
    bat, ctun = _telemetry(lambda second: 20 if second == 9 else 2,
                           lambda second: 70)
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None
    bat["Curr"] = 20
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None


def test_missing_throttle_and_corrupt_bat_do_not_qualify_t0():
    bat, ctun = _telemetry(lambda second: 2 if second < 8 else 20,
                           lambda second: 0)
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None
    ctun.loc[80, "ThO"] = 70
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None
    ctun.loc[80:, "ThO"] = 70
    bat.loc[80, "TimeUS"] = float("nan")
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None


def test_unrelated_late_current_burst_does_not_establish_launch_t0():
    bat, ctun = _telemetry(lambda second: 2 if second < 14.5 else 20,
                           lambda second: 70 if second >= 14.5 else 0)
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None


def test_throttle_ending_before_current_rise_does_not_qualify_t0():
    bat, ctun = _telemetry(
        lambda second: 2 if second < 10 else 20,
        lambda second: 70 if 9 <= second <= 9.3 else 0,
    )
    assert detect_pilot_load_onset(bat, 0, 10_000_000, ctun).t0_us is None


def test_gps_anchored_observation_never_reports_sag_or_recovery():
    bat, _ = _telemetry(lambda second: 5 if second < 12 else 20,
                        lambda second: 0)
    observed = observe_gps_anchored_bat(bat, 0, 10_000_000, 30_000_000)
    assert observed is not None
    assert observed.start_us == 10_000_000
    assert observed.end_us == 30_000_000
    assert observed.raw_peak_current_a == pytest.approx(20)
    assert observed.minimum_voltage_v == pytest.approx(15)
    assert "no T0, sag, T1 or recovery" in observed.status


def test_gps_anchored_missing_voltage_is_partial_observation():
    bat, _ = _telemetry(lambda second: 5 if second < 12 else 20,
                        lambda second: 0)
    bat.loc[150, "Volt"] = float("nan")
    observed = observe_gps_anchored_bat(bat, 0, 10_000_000, 30_000_000)
    assert observed is not None
    assert observed.raw_peak_current_a == pytest.approx(20)
    assert observed.minimum_voltage_v == pytest.approx(15)
    assert "partial observations" in observed.status
    assert "missing voltage/current" in observed.status
    assert "No T0, sag, T1 or recovery inferred" in observed.status
