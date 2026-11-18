"""Focused checks for bounded Battery Load-Event Analysis."""

import math

import pandas as pd
from analyses.battery import BatteryAnalysisPresentation
from core.battery import (
    BatteryLoadEventType,
    BatteryProcessor,
    TakeoffType,
)
from core.config import Config
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.flight_window_detector import FlightWindowDetector
from core.params import ParameterChange, ParameterHistory

CONFIG = Config("Config/battery.yaml")
WINDOW = FlightWindow(start_us=10_000_000, end_us=30_000_000)


def default_history(
    low_voltage=13.0,
    critical_voltage=12.0,
    failsafe_voltage_source=0.0,
):
    """Return primary-battery configuration for synthetic tests."""
    return ParameterHistory(
        {
            "BATT_CAPACITY": 5000.0,
            "BATT_LOW_VOLT": low_voltage,
            "BATT_CRT_VOLT": critical_voltage,
            "BATT_FS_VOLTSRC": failsafe_voltage_source,
        }
    )


def flight_log(messages, windows=None, history=None):
    """Build a compact FlightLog with registered FlightWindows."""
    return FlightLog(
        messages={name: pd.DataFrame(rows) for name, rows in messages.items()},
        parameter_history=history or default_history(),
        flights=windows or [WINDOW],
    )


def battery_rows():
    """Return same-instance event evidence plus a distracting instance."""
    return [
        {
            "TimeUS": 9_000_000,
            "Inst": 0,
            "Volt": 16.0,
            "Curr": 1.0,
            "CurrTot": 100.0,
            "EnrgTot": 1.0,
        },
        {
            "TimeUS": 10_000_000,
            "Inst": 0,
            "Volt": 15.5,
            "Curr": 2.0,
            "CurrTot": 101.0,
            "EnrgTot": 1.1,
        },
        {
            "TimeUS": 12_000_000,
            "Inst": 0,
            "Volt": 14.0,
            "Curr": 7.0,
            "CurrTot": 105.0,
            "EnrgTot": 1.2,
        },
        {
            "TimeUS": 12_000_000,
            "Inst": 1,
            "Volt": 1.0,
            "Curr": 99.0,
            "CurrTot": 900.0,
            "EnrgTot": 90.0,
        },
        {
            "TimeUS": 18_000_000,
            "Inst": 0,
            "Volt": 15.0,
            "Curr": 10.0,
            "CurrTot": 110.0,
            "EnrgTot": 1.4,
        },
        {
            "TimeUS": 22_999_999,
            "Inst": 0,
            "Volt": 14.8,
            "Curr": 3.0,
            "CurrTot": 112.0,
            "EnrgTot": 1.5,
        },
        {
            "TimeUS": 23_000_000,
            "Inst": 0,
            "Volt": 15.2,
            "Curr": 2.0,
            "CurrTot": 112.1,
            "EnrgTot": 1.6,
        },
    ]


def analyse(messages, history=None, window=WINDOW):
    """Run BatteryProcessor for primary instance zero."""
    log = flight_log(messages, windows=[window], history=history)
    result = BatteryProcessor(log, window, 0, config=CONFIG).analyse()
    assert result is not None
    return result


def sustained_events(result):
    return [
        event
        for event in result.bounded_load_events
        if event.event_type == BatteryLoadEventType.SUSTAINED_HIGH_THROTTLE
    ]


def takeoff_events(result):
    return [
        event
        for event in result.bounded_load_events
        if event.event_type == BatteryLoadEventType.TAKEOFF
    ]


def test_sustained_threshold_duration_and_separate_runs():
    result = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
                {"TimeUS": 18_100_000, "ThO": 89.999},
                {"TimeUS": 20_000_000, "ThO": 95.0},
                {"TimeUS": 28_000_000, "ThO": 95.0},
                {"TimeUS": 28_100_000, "ThO": 0.0},
            ],
        }
    )

    events = sustained_events(result)
    assert len(events) == 2
    assert [(event.start_us, event.end_us) for event in events] == [
        (10_000_000, 18_000_000),
        (20_000_000, 28_000_000),
    ]
    assert all(event.duration_s == 8.0 for event in events)


def test_sustained_just_below_duration_is_excluded():
    result = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 100.0},
                {"TimeUS": 17_999_973, "ThO": 100.0},
                {"TimeUS": 18_100_000, "ThO": 0.0},
            ],
        }
    )
    assert sustained_events(result) == []


def test_sustained_load_does_not_bridge_flights_or_ground_activity():
    first = FlightWindow(10_000_000, 20_000_000)
    second = FlightWindow(30_000_000, 40_000_000)
    messages = {
        "BAT": [
            {
                "TimeUS": time_us,
                "Inst": 0,
                "Volt": 15.0,
                "Curr": 10.0,
                "CurrTot": float(time_us / 1_000_000),
                "EnrgTot": 1.0,
            }
            for time_us in (
                10_000_000,
                20_000_000,
                30_000_000,
                40_000_000,
            )
        ],
        "CTUN": [
            {"TimeUS": 15_000_000, "ThO": 100.0},
            {"TimeUS": 19_000_000, "ThO": 100.0},
            {"TimeUS": 25_000_000, "ThO": 100.0},
            {"TimeUS": 31_000_000, "ThO": 100.0},
            {"TimeUS": 35_000_000, "ThO": 100.0},
        ],
    }
    log = flight_log(messages, windows=[first, second])

    for window in log.flights:
        result = BatteryProcessor(
            log,
            window,
            0,
            config=CONFIG,
        ).analyse()
        assert result is not None
        assert sustained_events(result) == []


def test_bounded_event_battery_metrics():
    result = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 100.0},
                {"TimeUS": 18_100_000, "ThO": 0.0},
            ],
        }
    )
    event = sustained_events(result)[0]

    assert event.instance == 0
    assert event.flight_number == 1
    assert event.consumed_mah_at_start == 101.0
    assert event.pre_load_voltage == 16.0
    assert event.minimum_voltage == 14.0
    assert event.current_at_minimum_voltage == 7.0
    assert event.peak_current == 10.0
    assert math.isclose(event.average_current, 19.0 / 3.0)
    assert event.maximum_throttle == 100.0
    assert event.average_throttle == 95.0
    assert event.voltage_sag == 2.0
    assert event.recovery_time_us == 23_000_000
    assert event.voltage_after_recovery == 15.2
    assert math.isclose(event.voltage_recovery, 1.2)
    assert event.low_voltage_margin == 1.0
    assert event.critical_voltage_margin == 2.0


def test_counter_reset_and_nonfinite_evidence_are_unavailable():
    rows = battery_rows()
    rows.insert(
        1,
        {
            "TimeUS": 9_500_000,
            "Inst": 0,
            "Volt": 16.0,
            "Curr": 1.0,
            "CurrTot": 50.0,
            "EnrgTot": 1.0,
        },
    )
    result = analyse(
        {
            "BAT": rows,
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        }
    )
    assert sustained_events(result)[0].consumed_mah_at_start is None

    unavailable = analyse(
        {
            "BAT": [
                {
                    "TimeUS": 9_000_000,
                    "Inst": 0,
                    "Volt": math.nan,
                    "Curr": 1.0,
                },
                {
                    "TimeUS": 10_000_000,
                    "Inst": 0,
                    "Volt": math.inf,
                    "Curr": math.inf,
                },
                {
                    "TimeUS": 18_000_000,
                    "Inst": 0,
                    "Volt": -math.inf,
                    "Curr": math.nan,
                },
                {
                    "TimeUS": 23_000_000,
                    "Inst": 0,
                    "Volt": math.inf,
                    "Curr": 1.0,
                },
            ],
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        }
    )
    event = sustained_events(unavailable)[0]
    assert event.consumed_mah_at_start is None
    assert event.pre_load_voltage is None
    assert event.minimum_voltage is None
    assert event.current_at_minimum_voltage is None
    assert event.peak_current is None
    assert event.average_current is None
    assert event.voltage_after_recovery is None
    assert event.voltage_recovery is None


def test_recovery_does_not_escape_flight():
    short_window = FlightWindow(
        start_us=10_000_000,
        end_us=22_000_000,
    )
    result = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        },
        window=short_window,
    )
    event = sustained_events(result)[0]
    assert event.recovery_time_us is None
    assert event.voltage_after_recovery is None
    assert event.voltage_recovery is None


def test_disabled_and_unsupported_threshold_margins():
    messages = {
        "BAT": battery_rows(),
        "CTUN": [
            {"TimeUS": 10_000_000, "ThO": 90.0},
            {"TimeUS": 18_000_000, "ThO": 90.0},
        ],
    }
    disabled = analyse(
        messages,
        history=default_history(
            low_voltage=0.0,
            critical_voltage=0.0,
        ),
    )
    assert disabled.session_configuration.low_voltage == 0.0
    assert disabled.session_configuration.critical_voltage == 0.0
    assert sustained_events(disabled)[0].low_voltage_margin is None
    assert sustained_events(disabled)[0].critical_voltage_margin is None

    unsupported = analyse(
        messages,
        history=default_history(failsafe_voltage_source=1.0),
    )
    assert unsupported.session_configuration.raw_voltage_margins_supported is False
    assert sustained_events(unsupported)[0].low_voltage_margin is None
    assert sustained_events(unsupported)[0].critical_voltage_margin is None


def test_session_configuration_rejects_later_changes():
    history = ParameterHistory(
        {
            "BATT_CAPACITY": 5000.0,
            "BATT_LOW_VOLT": 13.0,
            "BATT_CRT_VOLT": 12.0,
            "BATT_FS_VOLTSRC": 0.0,
        },
        {"BATT_LOW_VOLT": (ParameterChange(15_000_000, 12.5),)},
    )
    result = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [],
        },
        history=history,
    )
    configuration = result.session_configuration
    assert configuration.lookup_time_us == WINDOW.start_us
    assert configuration.capacity_mah == 5000.0
    assert configuration.low_voltage is None
    assert configuration.critical_voltage == 12.0
    assert configuration.warnings == (
        "BATT_LOW_VOLT changes after session configuration lookup.",
    )


def test_missing_and_nonfinite_session_configuration_is_unavailable():
    history = ParameterHistory(
        {
            "BATT_CAPACITY": math.nan,
            "BATT_LOW_VOLT": math.inf,
            "BATT_FS_VOLTSRC": -math.inf,
        }
    )
    result = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        },
        history=history,
    )
    configuration = result.session_configuration
    assert configuration.capacity_mah is None
    assert configuration.low_voltage is None
    assert configuration.critical_voltage is None
    assert configuration.failsafe_voltage_source is None
    assert sustained_events(result)[0].low_voltage_margin is None
    assert sustained_events(result)[0].critical_voltage_margin is None


def test_non_primary_instance_configuration_and_margins_are_unavailable():
    log = flight_log(
        {
            "BAT": [
                {
                    "TimeUS": time_us,
                    "Inst": 1,
                    "Volt": voltage,
                    "Curr": 10.0,
                    "CurrTot": float(time_us / 1_000_000),
                    "EnrgTot": 1.0,
                }
                for time_us, voltage in (
                    (9_000_000, 16.0),
                    (10_000_000, 15.0),
                    (18_000_000, 14.0),
                    (23_000_000, 15.0),
                )
            ],
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        }
    )
    result = BatteryProcessor(log, WINDOW, 1, config=CONFIG).analyse()
    assert result is not None

    configuration = result.session_configuration
    assert configuration.capacity_mah is None
    assert configuration.low_voltage is None
    assert configuration.critical_voltage is None
    assert configuration.failsafe_voltage_source is None
    assert configuration.warnings == (
        "Embedded battery configuration is unavailable for BAT instance 1.",
    )
    event = sustained_events(result)[0]
    assert event.instance == 1
    assert event.low_voltage_margin is None
    assert event.critical_voltage_margin is None


def test_auto_takeoff_bounds_and_flight_association():
    first = FlightWindow(20_000_000, 40_000_000)
    second = FlightWindow(60_000_000, 80_000_000)
    messages = {
        "BAT": [
            {
                "TimeUS": time_us,
                "Inst": 0,
                "Volt": 15.0,
                "Curr": 10.0,
                "CurrTot": float(time_us / 1_000_000),
                "EnrgTot": 1.0,
            }
            for time_us in (
                14_000_000,
                20_000_000,
                25_000_000,
                30_000_000,
                54_000_000,
                60_000_000,
                70_000_000,
                75_000_000,
            )
        ],
        "MODE": [
            {"TimeUS": 5_000_000, "ModeNum": 5},
            {"TimeUS": 10_000_000, "ModeNum": 13},
            {"TimeUS": 25_000_000, "ModeNum": 5},
            {"TimeUS": 50_000_000, "ModeNum": 13},
            {"TimeUS": 70_000_000, "ModeNum": 5},
        ],
        "MSG": [
            {"TimeUS": 15_000_000, "Message": "Triggered AUTO. GPS speed = 2.0"},
            {"TimeUS": 55_000_000, "Message": "Triggered AUTO. GPS speed = 2.2"},
        ],
        "CTUN": [],
    }
    log = flight_log(messages, windows=[first, second])

    first_result = BatteryProcessor(
        log,
        first,
        0,
        config=CONFIG,
    ).analyse()
    second_result = BatteryProcessor(
        log,
        second,
        0,
        config=CONFIG,
    ).analyse()
    assert first_result is not None
    assert second_result is not None

    first_event = takeoff_events(first_result)[0]
    second_event = takeoff_events(second_result)[0]
    assert (
        first_event.start_us,
        first_event.end_us,
        first_event.flight_number,
    ) == (20_000_000, 25_000_000, 1)
    assert (
        second_event.start_us,
        second_event.end_us,
        second_event.flight_number,
    ) == (60_000_000, 70_000_000, 2)
    assert first_event.takeoff_type == TakeoffType.AUTO
    assert second_event.takeoff_type == TakeoffType.AUTO
    assert first_result.battery_load_response is not None
    assert first_result.battery_load_response.t0_us is None
    assert "Load onset unavailable" in first_result.battery_load_response.status
    assert first.start_us <= first_event.start_us <= first_event.end_us <= first.end_us
    assert (
        second.start_us <= second_event.start_us <= second_event.end_us <= second.end_us
    )


def test_missing_or_ambiguous_auto_marker_does_not_invent_bounds():
    base = {
        "BAT": battery_rows(),
        "MODE": [
            {"TimeUS": 9_000_000, "ModeNum": 13},
            {"TimeUS": 20_000_000, "ModeNum": 5},
        ],
        "CTUN": [],
    }

    missing = analyse({**base, "MSG": []})
    assert takeoff_events(missing) == []

    ambiguous = analyse(
        {
            **base,
            "MSG": [
                {"TimeUS": 9_500_000, "Message": "Triggered AUTO"},
                {"TimeUS": 9_600_000, "Message": "Triggered AUTO"},
            ],
        }
    )
    assert takeoff_events(ambiguous) == []

    no_exit = analyse(
        {
            **base,
            "MODE": [{"TimeUS": 9_000_000, "ModeNum": 13}],
            "MSG": [
                {"TimeUS": 9_500_000, "Message": "Triggered AUTO"},
            ],
        }
    )
    assert takeoff_events(no_exit) == []


def test_airborne_and_later_auto_retriggers_do_not_create_takeoff_events():
    airborne = analyse(
        {
            "BAT": battery_rows(),
            "MODE": [
                {"TimeUS": 9_000_000, "ModeNum": 13},
                {"TimeUS": 20_000_000, "ModeNum": 5},
            ],
            "MSG": [
                {"TimeUS": 15_000_000, "Message": "Triggered AUTO"},
            ],
            "CTUN": [],
        }
    )
    assert takeoff_events(airborne) == []

    modes = [
        {"TimeUS": 9_000_000, "ModeNum": 13},
        {"TimeUS": 12_000_000, "ModeNum": 5},
        {"TimeUS": 15_000_000, "ModeNum": 13},
        {"TimeUS": 20_000_000, "ModeNum": 5},
    ]
    later_only = analyse(
        {
            "BAT": battery_rows(),
            "MODE": modes,
            "MSG": [
                {"TimeUS": 16_000_000, "Message": "Triggered AUTO"},
            ],
            "CTUN": [],
        }
    )
    assert takeoff_events(later_only) == []

    initial_and_later = analyse(
        {
            "BAT": battery_rows(),
            "MODE": modes,
            "MSG": [
                {"TimeUS": 9_500_000, "Message": "Triggered AUTO"},
                {"TimeUS": 16_000_000, "Message": "Triggered AUTO"},
            ],
            "CTUN": [],
        }
    )
    events = takeoff_events(initial_and_later)
    assert len(events) == 1
    assert (events[0].start_us, events[0].end_us) == (
        WINDOW.start_us,
        12_000_000,
    )


def test_ground_auto_trigger_without_flight_window_is_rejected():
    log = FlightLog(
        messages={
            "GPS": pd.DataFrame(
                [
                    {"TimeUS": 1_000_000, "Spd": 0.0},
                    {"TimeUS": 5_000_000, "Spd": 1.0},
                    {"TimeUS": 10_000_000, "Spd": 0.0},
                ]
            ),
            "MODE": pd.DataFrame([{"TimeUS": 2_000_000, "ModeNum": 13}]),
            "MSG": pd.DataFrame([{"TimeUS": 3_000_000, "Message": "Triggered AUTO"}]),
        },
        parameter_history=default_history(),
    )
    log.flights = FlightWindowDetector().detect(log)
    assert log.flights == []


def test_optional_pack_id_is_presentation_only():
    without_pack = BatteryAnalysisPresentation()
    analysis_without_pack = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        }
    )
    with_pack = BatteryAnalysisPresentation(pack_id="Pack 1")
    analysis_with_pack = analyse(
        {
            "BAT": battery_rows(),
            "CTUN": [
                {"TimeUS": 10_000_000, "ThO": 90.0},
                {"TimeUS": 18_000_000, "ThO": 90.0},
            ],
        }
    )
    assert without_pack.pack_id is None
    assert with_pack.pack_id == "Pack 1"
    assert analysis_without_pack == analysis_with_pack
