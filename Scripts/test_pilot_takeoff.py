"""Portable evidence tests for read-only pilot-controlled takeoffs."""

import os
from pathlib import Path

import pandas as pd
import pytest
from analyses.battery import format_battery_report
from core.battery import BatteryProcessor, TakeoffType
from core.config import Config
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.log_reader import FlightReader
from core.pilot_battery_onset import detect_pilot_load_onset
from core.pilot_takeoff import detect_pilot_takeoffs
from test_support import require_log


def _log(*, modes=(5, 0), second=True, climb=True, ground=True, bat=True):
    end = 45 if second else 20
    gps, pos, ctun, battery = [], [], [], []
    for tick in range(end * 10 + 1):
        seconds = tick / 10
        first_air = 5 <= seconds < 18
        second_air = second and 25 <= seconds < 40
        flying = first_air or second_air
        speed = 8 if flying else (1 if ground else 4)
        if first_air and seconds >= 15:
            altitude = (18 - seconds) * (20 / 3)
        elif first_air:
            altitude = min((seconds - 5) * 2, 20)
        elif second_air:
            altitude = min((seconds - 25) * 2, 20)
        else:
            altitude = 0
        if not climb:
            altitude = 0
        current = 20 if (4 <= seconds < 10 or second and 24 <= seconds < 30) else 2
        gps.append({"TimeUS": tick * 100_000, "Spd": speed})
        pos.append({"TimeUS": tick * 100_000, "RelHomeAlt": altitude})
        ctun.append({"TimeUS": tick * 100_000,
                     "ThO": 70 if flying or 4 <= seconds < 5
                     or second and 24 <= seconds < 25 else 0})
        battery.append({"TimeUS": tick * 100_000, "Inst": 0,
                        "Volt": 14 if current > 2 else 16, "Curr": current})
    messages = {
        "GPS": pd.DataFrame(gps), "POS": pd.DataFrame(pos),
        "CTUN": pd.DataFrame(ctun),
        "MODE": pd.DataFrame([{"TimeUS": 0, "ModeNum": modes[0]}]
                             + ([{"TimeUS": 20_000_000, "ModeNum": modes[1]}]
                                if second else [])),
        "STAT": pd.DataFrame([{"TimeUS": 0, "isFlying": 1}]),
        "BAT": pd.DataFrame(battery) if bat else pd.DataFrame(),
    }
    return FlightLog(messages=messages, flights=[FlightWindow(5_000_000, end * 1_000_000)])


def test_manual_and_fbwa_repeated_in_one_window_without_rearming():
    log = _log()
    events = detect_pilot_takeoffs(log).events
    assert [(e.time_us, e.mode_name) for e in events] == [
        (5_000_000, "FBWA"), (25_000_000, "MANUAL")]
    assert all(e.flight_start_us == 5_000_000 for e in events)
    analysis = BatteryProcessor(log, log.flights[0], 0).analyse()
    assert analysis is not None
    assert len(analysis.pilot_controlled_takeoffs) == 2
    assert all(m.takeoff_type is TakeoffType.PILOT_CONTROLLED
               for m in analysis.pilot_controlled_takeoffs)
    report = format_battery_report(Path("synthetic.bin"), log.flights[0], analysis)
    assert "PILOT-CONTROLLED TAKEOFFS" in report
    assert "PILOT_CONTROLLED / FBWA" in report
    assert "PILOT_CONTROLLED / MANUAL" in report
    assert "T0 load onset" in report


@pytest.mark.parametrize("changes", [
    {"climb": False}, {"ground": False}, {"modes": (13, 13)},
])
def test_ground_run_go_around_and_auto_do_not_produce_pilot_takeoffs(changes):
    assert not detect_pilot_takeoffs(_log(second=False, **changes)).events


def test_stationary_motor_runup_and_taxi_are_rejected():
    log = _log(second=False, climb=False)
    log.messages["CTUN"]["ThO"] = 80
    log.messages["BAT"]["Curr"] = 25
    assert not detect_pilot_takeoffs(log).events
    log.messages["GPS"]["Spd"] = 3
    assert not detect_pilot_takeoffs(log).events


def test_in_flight_throttle_rise_does_not_create_another_takeoff():
    log = _log(second=False)
    log.messages["GPS"].loc[100:109, "Spd"] = 3
    log.messages["CTUN"].loc[110:, "ThO"] = 90
    assert len(detect_pilot_takeoffs(log).events) == 1


@pytest.mark.parametrize("offset_m", [-20, -12, 12, 20])
def test_takeoff_from_elevated_or_lower_local_ground_is_confirmed(offset_m):
    log = _log()
    log.messages["POS"]["RelHomeAlt"] += offset_m
    assert [event.time_us for event in detect_pilot_takeoffs(log).events] == [
        5_000_000, 25_000_000]


def test_second_takeoff_from_elevated_remote_site_uses_its_local_ground():
    log = _log()
    pos = log.messages["POS"]
    seconds = pos["TimeUS"] / 1_000_000
    pos.loc[(seconds >= 5) & (seconds < 15), "RelHomeAlt"] = (
        (seconds[(seconds >= 5) & (seconds < 15)] - 5) * 4).clip(upper=40)
    pos.loc[(seconds >= 15) & (seconds < 18), "RelHomeAlt"] = (
        20 + (18 - seconds[(seconds >= 15) & (seconds < 18)]) * (20 / 3))
    pos.loc[seconds >= 18, "RelHomeAlt"] += 20
    events = detect_pilot_takeoffs(log).events
    assert [event.time_us for event in events] == [5_000_000, 25_000_000]
    assert events[1].ground_altitude_m == pytest.approx(20)


def test_airborne_speed_dip_with_continuing_thrust_is_not_a_new_takeoff():
    log = _log(second=False)
    gps = log.messages["GPS"]
    pos = log.messages["POS"]
    gps.loc[gps["TimeUS"] < 10_000_000, "Spd"] = 8
    gps.loc[(gps["TimeUS"] >= 10_000_000)
            & (gps["TimeUS"] < 12_000_000), "Spd"] = 1
    pos["RelHomeAlt"] = 1.0
    pos.loc[pos["TimeUS"] >= 12_000_000, "RelHomeAlt"] = (
        (pos.loc[pos["TimeUS"] >= 12_000_000, "TimeUS"] - 12_000_000)
        / 500_000 + 1)
    log.messages["CTUN"]["ThO"] = 75
    assert not detect_pilot_takeoffs(log).events
    log.messages["CTUN"].loc[110, "ThO"] = 0
    assert not detect_pilot_takeoffs(log).events


def test_headwind_slowdown_with_brief_power_reduction_is_not_a_relaunch():
    log = _log(second=False)
    gps = log.messages["GPS"]
    pos = log.messages["POS"]
    ctun = log.messages["CTUN"]
    gps.loc[120:159, "Spd"] = 1
    pos.loc[120:159, "RelHomeAlt"] = 18.0
    pos.loc[160:, "RelHomeAlt"] = 18 + (pos.loc[160:, "TimeUS"] - 16_000_000) / 500_000
    ctun.loc[130:142, "ThO"] = 5
    assert [event.time_us for event in detect_pilot_takeoffs(log).events] == [5_000_000]


def test_stable_airborne_altitude_then_climb_lacks_landing_descent():
    log = _log(second=False)
    gps = log.messages["GPS"]
    pos = log.messages["POS"]
    gps.loc[100:159, "Spd"] = 1
    pos.loc[100:159, "RelHomeAlt"] = 12.0
    pos.loc[160:, "RelHomeAlt"] = 12 + (pos.loc[160:, "TimeUS"] - 16_000_000) / 500_000
    log.messages["CTUN"].loc[100:120, "ThO"] = 0
    assert [event.time_us for event in detect_pilot_takeoffs(log).events] == [5_000_000]


def test_rapid_relaunch_requires_recorded_descent_and_ground_plateau():
    log = _log()
    events = detect_pilot_takeoffs(log).events
    assert [event.time_us for event in events] == [5_000_000, 25_000_000]
    assert "Relaunch after" in events[1].ground_evidence
    log.messages["POS"].loc[150:249, "RelHomeAlt"] = 20
    log.messages["POS"].loc[250:, "RelHomeAlt"] += 20
    assert [event.time_us for event in detect_pilot_takeoffs(log).events] == [5_000_000]


def test_relaunch_rejects_corrupt_landing_descent_evidence():
    log = _log()
    log.messages["POS"].loc[165, "TimeUS"] = float("nan")
    assert [event.time_us for event in detect_pilot_takeoffs(log).events] == [5_000_000]


def test_taxi_power_before_initial_launch_does_not_require_prior_landing():
    log = _log(second=False)
    log.messages["GPS"].loc[:20, "Spd"] = 3
    log.messages["CTUN"].loc[:20, "ThO"] = 30
    events = detect_pilot_takeoffs(log).events
    assert [event.time_us for event in events] == [5_000_000]
    assert "Initial ground launch" in events[0].ground_evidence


def test_fast_taxi_then_slow_ground_period_does_not_claim_real_takeoff_climb():
    log = _log(second=False)
    gps = log.messages["GPS"]
    pos = log.messages["POS"]
    ctun = log.messages["CTUN"]
    seconds = gps["TimeUS"] / 1_000_000
    gps["Spd"] = 1
    gps.loc[(seconds >= 2) & (seconds < 5), "Spd"] = 6
    gps.loc[seconds >= 11, "Spd"] = 8
    pos["RelHomeAlt"] = ((pos["TimeUS"] / 1_000_000 - 11) * 2).clip(lower=0, upper=20)
    ctun["ThO"] = 0
    ctun.loc[(seconds >= 2) & (seconds < 5), "ThO"] = 70
    ctun.loc[seconds >= 11, "ThO"] = 70
    log.flights = [FlightWindow(2_000_000, 20_000_000)]
    scan = detect_pilot_takeoffs(log)
    assert [event.time_us for event in scan.events] == [11_000_000]
    assert any(candidate.time_us == 2_000_000 and "ground state" in candidate.reason
               for candidate in scan.rejected)
    assert "Initial ground launch" in scan.events[0].ground_evidence


def test_gap_after_climb_proof_does_not_veto_confirmed_takeoff():
    log = _log(second=False)
    log.messages["POS"] = log.messages["POS"].drop(index=range(180, 191))
    assert [event.time_us for event in detect_pilot_takeoffs(log).events] == [5_000_000]


def test_gap_during_climb_proof_rejects_takeoff():
    log = _log(second=False)
    log.messages["POS"] = log.messages["POS"].drop(index=range(105, 112))
    assert not detect_pilot_takeoffs(log).events


def test_throttle_first_applied_four_seconds_after_acceleration_is_not_launch_proof():
    log = _log(second=False)
    log.messages["CTUN"].loc[:93, "ThO"] = 0
    assert not detect_pilot_takeoffs(log).events


def test_touchdown_then_continued_taxi_is_not_a_second_takeoff():
    log = _log()
    log.messages["GPS"].loc[250:, "Spd"] = 3
    log.messages["POS"].loc[250:, "RelHomeAlt"] = 0
    log.messages["CTUN"].loc[250:, "ThO"] = 35
    assert len(detect_pilot_takeoffs(log).events) == 1


@pytest.mark.parametrize("missing", ["GPS", "POS"])
def test_missing_essential_telemetry_is_rejected(missing):
    log = _log(second=False)
    log.messages.pop(missing)
    scan = detect_pilot_takeoffs(log)
    assert not scan.events
    assert scan.rejected


def test_invalid_timestamp_and_interrupted_gps_confirmation_are_rejected():
    log = _log(second=False)
    log.messages["POS"].loc[55, "TimeUS"] = float("nan")
    assert not detect_pilot_takeoffs(log).events
    log = _log(second=False)
    log.messages["GPS"] = log.messages["GPS"].drop(index=range(55, 64))
    assert not detect_pilot_takeoffs(log).events


def test_confirmed_takeoff_survives_missing_bat_baseline():
    log = _log(second=False)
    log.messages["BAT"].loc[:40, "Curr"] = 20
    analysis = BatteryProcessor(log, log.flights[0], 0).analyse()
    assert len(analysis.pilot_controlled_takeoffs) == 1
    measurement = analysis.pilot_controlled_takeoffs[0]
    response = measurement.response
    assert response.t0_us is None
    assert response.voltage_drop_v is None
    assert measurement.gps_observation is not None
    report = format_battery_report(Path("synthetic.bin"), log.flights[0], analysis)
    assert "GPS-ANCHORED BAT OBSERVATION (separate from T0-based response)" in report
    assert "no T0, sag, T1 or recovery inferred" in report


def test_adjacent_analysis_scopes_do_not_duplicate_takeoff():
    log = _log(second=False)
    log.flights = [FlightWindow(5_000_000, 10_000_000),
                   FlightWindow(10_000_001, 20_000_000)]
    counts = [len(BatteryProcessor(log, window, 0).analyse().pilot_controlled_takeoffs)
              for window in log.flights]
    assert counts == [1, 0]


@pytest.mark.parametrize("name,modes,seconds,onsets,rejections", [
    ("log_61_2026-10-25-10-45-48Pc.bin", ("FBWA", "FBWA", "FBWA"),
     (711.64, 1081.42, 1361.68), (712.10, 1080.70, 1360.70), 25),
    ("log_63_2026-10-25-11-24-56Pc.bin", ("FBWA", "FBWA", "FBWA"),
     (163.48, 436.16, 666.14), (162.96, 435.36, 663.56), 19),
    ("log_73_2026-11-15-09-27-30Pc.bin", ("MANUAL", "FBWA"),
     (434.34, 929.46), (435.12, 929.42), 1),
    ("log_74_2026-11-15-09-56-12Pc.bin", ("FBWA",), (148.69,), (147.61,), 1),
    ("log_3_2026-11-15-10-58-12Rg.bin", (), (), (), 3),
])
def test_five_log_pilot_takeoff_replay(name, modes, seconds, onsets, rejections):
    directory = Path(os.environ.get("APT_REAL_LOG_DIR", "Logs"))
    log = FlightReader(require_log(directory / name),
                       config=Config("Config/battery.yaml")).read()
    scan = detect_pilot_takeoffs(log)
    assert tuple(event.mode_name for event in scan.events) == modes
    assert len(scan.rejected) == rejections
    assert tuple(event.time_us / 1_000_000 for event in scan.events) == pytest.approx(
        seconds, abs=0.15)
    qualified = [detect_pilot_load_onset(log.get("BAT"), 0, event.time_us,
                                         log.get("CTUN")) for event in scan.events]
    assert tuple(onset.t0_us / 1_000_000 for onset in qualified) == pytest.approx(
        onsets, abs=0.15)
    if "log_63_" in name:
        assert scan.events[1].flight_start_us == scan.events[2].flight_start_us
