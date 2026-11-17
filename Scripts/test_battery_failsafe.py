"""Synthetic and optional Piper regressions for Battery Analysis failsafe evidence."""

import os
from pathlib import Path

import pandas as pd
import pytest
from analyses.battery import format_battery_report
from core.battery import BatteryProcessor
from core.battery_failsafe import assess_voltage_failsafe
from core.config import Config
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.log_reader import FlightReader
from core.params import ParameterChange, ParameterHistory

CONFIG = Config("Config/battery.yaml")
WINDOW = FlightWindow(0, 2_000_000)
PARAMS = {
    "BATT_LOW_VOLT": 14.4,
    "BATT_CRT_VOLT": 13.6,
    "BATT_LOW_TIMER": 0.2,
    "BATT_FS_VOLTSRC": 0,
    "BATT_FS_LOW_ACT": 1,
    "BATT_FS_CRT_ACT": 1,
    "BATT_LOW_MAH": 0,
    "BATT_CRT_MAH": 0,
    "BATT2_LOW_VOLT": 14.4,
    "BATT2_CRT_VOLT": 13.6,
    "BATT2_LOW_TIMER": 0.2,
    "BATT2_FS_VOLTSRC": 1,
}


def _row(time_s, instance=0, raw=14.0, resting=15.0, current=10.0, health=1):
    return {
        "TimeUS": round(time_s * 1_000_000),
        "Inst": instance,
        "Volt": raw,
        "VoltR": resting,
        "Curr": current,
        "CurrTot": 1000 + time_s * 10,
        "Res": 0.1,
        "H": health,
    }


def _log(rows, *, arms=None, messages=None, modes=None, history=None, windows=None):
    return FlightLog(
        messages={
            "BAT": pd.DataFrame(rows),
            "ARM": pd.DataFrame(arms or []),
            "MSG": pd.DataFrame(messages or []),
            "MODE": pd.DataFrame(modes or []),
        },
        parameter_history=history or ParameterHistory(PARAMS),
        flights=windows or [WINDOW],
    )


def test_raw_replay_and_observed_rtl_are_distinct_in_battery_report():
    """A logged battery message confirms the event independently of replay."""
    log = _log(
        [_row(0), _row(0.1), _row(0.2)],
        arms=[{"TimeUS": 0, "ArmState": 1}],
        messages=[
            {"TimeUS": 210_000, "Message": "Battery 1 is low 14.0V used 1002 mAh"}
        ],
        modes=[{"TimeUS": 220_000, "ModeNum": 11, "Rsn": 4}],
    )
    analysis = BatteryProcessor(log, WINDOW, 0, CONFIG).analyse()
    assert analysis is not None
    evidence = analysis.voltage_failsafe
    raw = [
        event
        for event in evidence.excursions
        if event.source == "raw" and event.stage == "low"
    ]
    assert len(raw) == 1
    assert raw[0].first_qualification_us == 200_000
    assert raw[0].armed_session == 1
    assert not [event for event in evidence.excursions if event.source == "compensated"]
    assert len(evidence.observed) == 1
    assert evidence.observed[0].mode_number == 11
    report = format_battery_report(Path("synthetic.bin"), WINDOW, analysis)
    assert "VOLTAGE FAILSAFE ASSESSMENT" in report
    assert "Replay (recorded source)" in report
    assert "Battery-low message with correlated RTL (MODE reason 4)" in report
    assert "Voltage after 5 s" in report


def test_gap_parameter_change_and_arm_sessions_split_low_runs():
    """No timer borrows time across a gap, changed rule, or rearming."""
    rows = [_row(t) for t in (0, 0.1, 0.6, 0.7, 0.8, 0.9)]
    history = ParameterHistory(
        PARAMS,
        {
            "BATT_LOW_VOLT": (ParameterChange(650_000, 14.2),),
        },
    )
    log = _log(
        rows,
        history=history,
        arms=[
            {"TimeUS": 0, "ArmState": 1},
            {"TimeUS": 750_000, "ArmState": 0},
            {"TimeUS": 850_000, "ArmState": 1},
        ],
    )
    events = [
        event
        for event in assess_voltage_failsafe(log, 0).excursions
        if event.source == "raw" and event.stage == "low"
    ]
    assert len(events) == 5
    assert all(event.first_qualification_us is None for event in events)
    assert events[0].gap_after
    assert events[1].configuration.low_v == 14.4
    assert events[2].configuration.low_v == 14.2


def test_unhealthy_compensation_is_unavailable_and_monitor_policy_is_independent():
    """A false BAT.H or invalid VoltR cannot count as evidence of safety."""
    rows = [
        _row(0, health=0),
        _row(0.1, health=0),
        _row(0.2, health=0),
        _row(0, instance=1),
        _row(0.1, instance=1),
        _row(0.2, instance=1),
    ]
    log = _log(rows)
    first = assess_voltage_failsafe(log, 0)
    second = assess_voltage_failsafe(log, 1)
    assert first.compensation_unavailable
    assert not any(event.source == "compensated" for event in first.excursions)
    assert not second.compensation_unavailable
    assert all(event.configuration.source == 1 for event in second.excursions)
    assert any(
        event.source == "raw" and not event.selected_source
        for event in second.excursions
    )


def test_zero_timer_and_out_of_order_samples_do_not_qualify():
    """A disabled timer and reversed timestamps cannot produce a trigger."""
    log = _log(
        [_row(0), _row(0.1), _row(0.05), _row(0.15)],
        history=ParameterHistory({**PARAMS, "BATT_LOW_TIMER": 0}),
    )
    assert not assess_voltage_failsafe(log, 0).excursions
    log.parameter_history = ParameterHistory(PARAMS)
    events = [
        event
        for event in assess_voltage_failsafe(log, 0).excursions
        if event.source == "raw" and event.stage == "low"
    ]
    assert len(events) == 2
    assert all(event.first_qualification_us is None for event in events)


def test_missing_current_blocks_compensation_and_warning_only_stays_observed():
    """Missing compensation evidence cannot imply safety or an RTL action."""
    log = _log(
        [
            _row(0, current=float("nan")),
            _row(0.1, current=float("nan")),
            _row(0.2, current=float("nan")),
        ],
        messages=[
            {"TimeUS": 210_000, "Message": "Battery 1 is low 14.0V used 1002 mAh"}
        ],
    )
    assessment = assess_voltage_failsafe(log, 0)
    assert assessment.compensation_unavailable
    assert not any(event.source == "compensated" for event in assessment.excursions)
    assert len(assessment.observed) == 1
    assert assessment.observed[0].mode_number is None
    analysis = BatteryProcessor(log, WINDOW, 0, CONFIG).analyse()
    report = format_battery_report(Path("warning.bin"), WINDOW, analysis)
    assert "Observed battery message" in report
    assert "Battery-low message with correlated RTL" not in report



def test_parameter_changed_then_restored_between_bat_samples_breaks_timer():
    """A transient PARM edit must not be invisible to BAT-sampled replay."""
    history = ParameterHistory(
        PARAMS,
        {
            "BATT_LOW_VOLT": (
                ParameterChange(50_000, 13.5),
                ParameterChange(150_000, 14.4),
            ),
        },
    )
    log = _log([_row(0), _row(0.2), _row(0.3)], history=history)
    raw = [
        e for e in assess_voltage_failsafe(log, 0).excursions
        if e.source == "raw" and e.stage == "low"
    ]
    assert len(raw) == 2
    assert [e.start_us for e in raw] == [0, 200_000]
    assert all(e.first_qualification_us is None for e in raw)


def test_flight_attribution_excludes_qualification_before_window():
    """An overlapping run is not a qualification *in* the selected flight."""
    log = _log([_row(t) for t in (0, 0.1, 0.2, 0.3, 0.4)])
    window = FlightWindow(250_000, 350_000)
    assessment = assess_voltage_failsafe(log, 0, window)
    raw = [
        e for e in assessment.excursions
        if e.source == "raw" and e.stage == "low"
    ]
    assert len(raw) == 1
    assert raw[0].start_us == 0  # full run retains historical evidence
    assert raw[0].first_qualification_us is None
    assert raw[0].qualification_outside_window == "before"
    full = assess_voltage_failsafe(log, 0)
    assert next(
        e for e in full.excursions if e.source == "raw" and e.stage == "low"
    ).first_qualification_us == 200_000
    from analyses.battery import format_voltage_failsafe_assessment

    report = format_voltage_failsafe_assessment(assessment)
    assert "qualification(s) outside selected flight" in report
    assert "first qualifies 00:00.200" not in report


def test_qualifying_from_before_window_counts_only_if_time_is_inside():
    """Do not reset the timer just because a flight boundary is crossed."""
    log = _log([_row(t) for t in (0, 0.1, 0.2, 0.3, 0.4)])
    during = assess_voltage_failsafe(log, 0, FlightWindow(150_000, 350_000))
    after = assess_voltage_failsafe(log, 0, FlightWindow(50_000, 150_000))
    def raw_events(assessment):
        return [
            e for e in assessment.excursions
            if e.source == "raw" and e.stage == "low"
        ]
    assert raw_events(during)[0].first_qualification_us == 200_000
    assert raw_events(after)[0].first_qualification_us is None
    assert raw_events(after)[0].qualification_outside_window == "after"


def test_missing_compensation_or_sampling_gap_never_means_zero_safe_triggers():
    """Zero observed qualifications is inconclusive when coverage is partial."""
    log = _log([
        _row(0, resting=float("nan")),
        _row(0.1, resting=float("nan")),
        _row(0.7, resting=float("nan")),
    ])
    assessment = assess_voltage_failsafe(log, 0)
    assert assessment.compensation_unavailable
    assert assessment.sampling_gaps
    from analyses.battery import format_voltage_failsafe_assessment

    report = format_voltage_failsafe_assessment(assessment)
    assert "qualification indeterminate" in report
    assert "unknown across gaps" in report
    assert "Capacity failsafe thresholds: low disabled, critical disabled" in report



def test_missing_raw_sample_is_indeterminate_not_zero_qualification():
    """Invalid BAT.Volt interrupts the timer and limits safety conclusions."""
    log = _log([
        _row(0),
        _row(0.1, raw=float("nan")),
        _row(0.2),
    ])
    assessment = assess_voltage_failsafe(log, 0)
    assert assessment.raw_unavailable
    from analyses.battery import format_voltage_failsafe_assessment

    report = format_voltage_failsafe_assessment(assessment)
    assert "Raw voltage partly unavailable" in report
    assert "Raw low: 2 excursions, qualification indeterminate" in report


def test_mode_correlation_prefers_battery_reason_over_nearer_unrelated_mode():
    """A coincident MODE change without battery reason is not confirmation."""
    log = _log(
        [_row(0), _row(0.1), _row(0.2)],
        messages=[{"TimeUS": 210_000, "Message": "Battery 1 is low 14.0V"}],
        modes=[
            {"TimeUS": 211_000, "ModeNum": 10, "Rsn": 2},
            {"TimeUS": 220_000, "ModeNum": 11, "Rsn": 4},
        ],
    )
    assessment = assess_voltage_failsafe(log, 0)
    assert assessment.observed[0].mode_number == 11
    assert assessment.observed[0].mode_reason == 4
    from analyses.battery import format_voltage_failsafe_assessment

    assert "temporal association, not proof of causation" in (
        format_voltage_failsafe_assessment(assessment)
    )

@pytest.mark.parametrize(
    "number, count, duration, qualified",
    [
        (61, 13, 13.2, 1795.7),
        (63, 0, None, None),
        (73, 17, 10.3, 1114.516),
        (74, 6, 10.2, 554.511),
    ],
)
def test_piper_logged_low_voltage_against_saved_audit(
    number, count, duration, qualified
):
    """Optional local BINs preserve the audit's raw event counts and timings."""
    root = Path(os.environ.get("APT_PIPER_LOG_DIR", "Logs"))
    paths = list(root.glob(f"log_{number}_*Pc.bin"))
    if not paths:
        pytest.skip(f"PC{number} BIN not available locally")
    log = FlightReader(paths[0], config=CONFIG).read()
    assessment = assess_voltage_failsafe(log, 0)
    raw = [
        event
        for event in assessment.excursions
        if event.source == "raw" and event.stage == "low"
    ]
    qualifying = [event for event in raw if event.first_qualification_us is not None]
    assert len(raw) == count
    if duration is not None:
        assert max(event.duration_s for event in raw) == pytest.approx(
            duration, abs=0.11
        )
        assert qualifying[0].first_qualification_us / 1_000_000 == pytest.approx(
            qualified, abs=0.11
        )
    else:
        assert not qualifying
    assert not [
        event
        for event in assessment.excursions
        if event.source == "compensated" and event.first_qualification_us is not None
    ]
    assert len(assessment.observed) == (0 if number == 63 else 1)
    if number == 61:
        actual_history = log.parameter_history
        log.parameter_history = ParameterHistory(
            {
                **actual_history.latest_values,
                "BATT_LOW_VOLT": 14.4,
            }
        )
        alternative = assess_voltage_failsafe(log, 0)
        log.parameter_history = actual_history
        compensated = [
            event
            for event in alternative.excursions
            if event.source == "compensated"
            and event.stage == "low"
            and event.first_qualification_us is not None
        ]
        assert len(compensated) == 5
        assert sum(event.armed_session is None for event in compensated) == 2
        assert compensated[0].first_qualification_us / 1_000_000 == pytest.approx(
            1649.7, abs=0.11
        )
