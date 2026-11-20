"""Portable evidence checks for observed pilot BAT plateau comparisons."""

import os
from pathlib import Path

import pandas as pd
import pytest
from core.battery import BatteryProcessor
from core.config import Config
from core.log_reader import FlightReader
from core.pilot_battery_onset import PilotLoadOnset
from core.pilot_plateau_voltage import evaluate_observed_plateau_voltage
from test_support import require_log


def _onset(t0=5_000_000, reference=20):
    return PilotLoadOnset(t0, "qualified", launch_reference_a=reference)


def _bat(pre=2, loaded=20, noise=0):
    return pd.DataFrame([
        {"TimeUS": tick * 100_000, "Inst": 0,
         "Curr": (pre if tick < 50 else loaded) + noise * (tick % 3 - 1),
         "Volt": (16 if tick < 50 else 15) + noise * 0.02 * (tick % 3 - 1)}
        for tick in range(101)
    ])


@pytest.mark.parametrize("pre,loaded,noise", [(2, 20, 0), (8, 28, 0), (3, 21, 0.1)])
def test_clean_and_noisy_plateaus(pre, loaded, noise):
    result = evaluate_observed_plateau_voltage(_bat(pre, loaded, noise), 0, _onset(), 8_000_000, 10_000_000)
    assert result.voltage_change_v == pytest.approx(1, abs=0.01)
    assert result.current_change_a == pytest.approx(loaded - pre, abs=0.2)
    assert result.pre_end_us < 5_000_000 <= result.loaded_start_us
    assert result.loaded_end_us <= 8_000_000


def test_recency_boundary_and_t1_truncation():
    bat = _bat()
    bat.loc[46:49, "Curr"] = [5, 8, 11, 14]
    bat.loc[46:49, "Volt"] = [15.8, 15.6, 15.4, 15.2]
    result = evaluate_observed_plateau_voltage(bat, 0, _onset(), 6_000_000, 10_000_000)
    assert result.voltage_change_v is not None
    assert result.pre_end_us == 4_500_000
    assert result.pre_to_t0_us == 500_000
    assert result.loaded_end_us <= 6_000_000


def test_gap_after_pre_plateau_does_not_qualify_comparison():
    bat = _bat().drop(index=range(46, 50))
    result = evaluate_observed_plateau_voltage(bat, 0, _onset(), None, 10_000_000)
    assert result.voltage_change_v is None
    assert "gap" in result.status


@pytest.mark.parametrize("offset_us,qualifies", [(146, True), (1_000, True),
                                                 (1_001, False)])
def test_recency_alignment_boundary(offset_us, qualifies):
    bat = _bat()
    bat.loc[46:49, "Curr"] = [5, 8, 11, 14]
    bat.loc[46:49, "Volt"] = [15.8, 15.6, 15.4, 15.2]
    bat.loc[50, "TimeUS"] = 5_000_000 + offset_us
    result = evaluate_observed_plateau_voltage(
        bat, 0, _onset(5_000_000 + offset_us), None, 10_000_000)
    assert (result.voltage_change_v is not None) is qualifies


def test_loaded_plateau_must_finish_inside_selected_flight():
    bat = _bat()
    short = evaluate_observed_plateau_voltage(bat, 0, _onset(), None, 5_600_000)
    assert short.voltage_change_v is None
    assert "FlightWindow" in short.status
    long = evaluate_observed_plateau_voltage(bat, 0, _onset(), None, 6_000_000)
    assert long.voltage_change_v == pytest.approx(1)
    assert long.loaded_end_us <= 6_000_000


@pytest.mark.parametrize("edit", [
    lambda b: b.loc.__setitem__((slice(41, 49), "Curr"), list(range(10, 19))),
    lambda b: b.drop(index=range(40, 48), inplace=True),
    lambda b: b.drop(index=range(42, 49), inplace=True),
    lambda b: b.loc.__setitem__((45, "TimeUS"), 4_100_000),
    lambda b: b.loc.__setitem__((45, "TimeUS"), 4_400_000),
    lambda b: b.loc.__setitem__((45, "TimeUS"), float("nan")),
    lambda b: b.loc.__setitem__((45, "Curr"), float("nan")),
    lambda b: b.loc.__setitem__((45, "Volt"), float("nan")),
])
def test_incomplete_or_staged_pre_onset_never_produces_value(edit):
    bat = _bat()
    edit(bat)
    assert evaluate_observed_plateau_voltage(bat, 0, _onset(), None, 10_000_000).voltage_change_v is None


def test_short_peak_and_insufficient_current_separation():
    bat = _bat()
    bat.loc[50:, "Curr"] = 3
    bat.loc[55, "Curr"] = 30
    assert evaluate_observed_plateau_voltage(bat, 0, _onset(), None, 10_000_000).voltage_change_v is None
    bat.loc[55, "Curr"] = 3
    assert "Insufficient current separation" in evaluate_observed_plateau_voltage(
        bat, 0, _onset(), None, 10_000_000).status


def test_no_loaded_plateau_before_t1_and_missing_t0():
    bat = _bat()
    assert evaluate_observed_plateau_voltage(bat, 0, _onset(), 5_700_000, 10_000_000).voltage_change_v is None
    assert evaluate_observed_plateau_voltage(bat, 0, _onset(None), None, 10_000_000).voltage_change_v is None
    assert evaluate_observed_plateau_voltage(bat, 0, _onset(reference=None), None, 10_000_000).voltage_change_v is None


@pytest.mark.parametrize("column,value", [("Curr", float("nan")),
                                          ("Volt", float("nan")),
                                          ("TimeUS", 5_100_000)])
def test_incomplete_loaded_transition_is_not_skipped(column, value):
    bat = _bat()
    bat.loc[53, column] = value
    result = evaluate_observed_plateau_voltage(bat, 0, _onset(), None, 10_000_000)
    assert result.voltage_change_v is None
    assert "Missing" in result.status or "gap" in result.status


def test_repeated_takeoffs_use_separate_windows():
    first = _bat()
    second = _bat(pre=6, loaded=26)
    second["TimeUS"] += 20_000_000
    bat = pd.concat((first, second), ignore_index=True)
    one = evaluate_observed_plateau_voltage(bat, 0, _onset(), 8_000_000, 10_000_000)
    two = evaluate_observed_plateau_voltage(bat, 0, _onset(25_000_000, 26), 28_000_000, 30_000_000)
    assert one.pre_current_a == pytest.approx(2)
    assert two.pre_current_a == pytest.approx(6)


@pytest.mark.parametrize("filename,expected", [
    ("log_61_2026-10-25-10-45-48Pc.bin", (None, 1.89, 2.21)),
    ("log_63_2026-10-25-11-24-56Pc.bin", (1.20, None, None)),
    ("log_73_2026-11-15-09-27-30Pc.bin", (1.81, 1.90)),
    ("log_74_2026-11-15-09-56-12Pc.bin", (None,)),
    ("log_3_2026-11-15-10-58-12Rg.bin", ()),
])
def test_five_log_plateau_replay(filename, expected):
    directory = Path(os.environ.get("APT_REAL_LOG_DIR", "Logs"))
    log = FlightReader(require_log(directory / filename),
                       config=Config("Config/battery.yaml")).read()
    measurements = []
    for flight in log.flights:
        analysis = BatteryProcessor(log, flight, 0).analyse()
        if analysis is not None:
            measurements.extend(analysis.pilot_controlled_takeoffs)
    assert len(measurements) == len(expected)
    assert all(measurement.onset.t0_us is not None for measurement in measurements)
    audit_medians = {
        "log_61_": {1: (7.73, 15.20, 32.26, 13.31),
                    2: (0.57, 15.20, 31.34, 12.99)},
        "log_63_": {0: (5.63, 16.18, 21.07, 14.98)},
        "log_73_": {0: (12.29, 15.51, 34.94, 13.70),
                    1: (9.63, 15.11, 31.68, 13.21)},
    }
    prefix = filename[:7]
    for index, (measurement, delta) in enumerate(zip(measurements, expected)):
        comparison = measurement.plateau_comparison
        assert comparison is not None
        if delta is None:
            if "log_63_" in filename:
                assert comparison.status == "No sufficiently recent pre-onset plateau."
                assert measurement.response.raw_peak_current_a is not None
                assert measurement.response.minimum_voltage_v is not None
            assert comparison.voltage_change_v is None or "log_63_" not in filename
        else:
            assert comparison.voltage_change_v == pytest.approx(delta, abs=0.04)
            values = (comparison.pre_current_a, comparison.pre_voltage_v,
                      comparison.loaded_current_a, comparison.loaded_voltage_v)
            for actual, target in zip(values, audit_medians[prefix][index]):
                assert actual == pytest.approx(target, abs=0.06)
    if prefix == "log_61_":
        assert measurements[0].response.voltage_drop_v == pytest.approx(2.30, abs=0.02)
    if prefix == "log_74_":
        assert measurements[0].response.voltage_drop_v == pytest.approx(1.30, abs=0.02)
