"""Regression tests for reusable Battery Analysis text presentation."""

from pathlib import Path
from types import SimpleNamespace

from analyses.battery import BatteryAnalysisPresentation, format_battery_report
from core.battery import BatteryLoadEventType, TakeoffType
from core.flight_window import FlightWindow


def _bounded_event(event_type=BatteryLoadEventType.TAKEOFF):
    return SimpleNamespace(
        event_type=event_type,
        takeoff_type=(
            TakeoffType.AUTO
            if event_type is BatteryLoadEventType.TAKEOFF
            else None
        ),
        start_us=2_000_000,
        end_us=5_250_000,
        duration_s=3.25,
        consumed_mah_at_start=12.345,
        maximum_throttle=98.765,
        average_throttle=91.234,
        pre_load_voltage=12.61,
        minimum_voltage=11.42,
        voltage_sag=1.19,
        peak_current=31.234,
        average_current=24.567,
        current_at_minimum_voltage=30.125,
        voltage_after_recovery=12.25,
        voltage_recovery=0.83,
        low_voltage_margin=0.92,
        critical_voltage_margin=1.42,
    )


def _analysis(*, configuration=True, bounded=True):
    session_configuration = (
        SimpleNamespace(
            capacity_mah=5000.0,
            low_voltage=10.5,
            critical_voltage=10.0,
            warnings=("BATT_CAPACITY changes after session configuration lookup.",),
        )
        if configuration
        else None
    )
    return SimpleNamespace(
        instance=0,
        duration_s=65.4,
        start_voltage=12.6,
        final_voltage=11.9,
        minimum_voltage=11.4,
        maximum_current=31.2,
        average_current=8.75,
        maximum_power=365.5,
        consumed_wh=5.25,
        consumed_mah=410.25,
        mah_per_minute=376.38,
        load_event=SimpleNamespace(
            time_us=3_000_000,
            current=31.2,
            voltage_before=12.6,
            minimum_voltage=11.4,
            voltage_sag=1.2,
            sag_per_ampere=0.038,
            voltage_after_recovery=12.2,
            voltage_recovery=0.8,
        ),
        counter_warnings=["CurrTot counter decreased within the flight window."],
        session_configuration=session_configuration,
        bounded_load_events=(
            [
                _bounded_event(),
                _bounded_event(BatteryLoadEventType.SUSTAINED_HIGH_THROTTLE),
            ]
            if bounded
            else []
        ),
    )


def test_battery_formatter_preserves_metrics_events_warnings_and_labels():
    report = format_battery_report(
        Path("battery.bin"),
        FlightWindow(1_000_000, 66_400_000),
        _analysis(),
        "Pack 1",
    )

    assert "Log    : battery.bin" in report
    assert "Window : 00:01.000 -> 01:06.400" in report
    assert "Battery instance : 0" in report
    assert "Pack ID          : Pack 1" in report
    assert "Capacity         : 5000 mAh" in report
    assert "Low voltage      : 10.50 V" in report
    assert "Critical voltage : 10.00 V" in report
    assert "Flight duration       01:05" in report
    assert "Maximum current       31.20 A" in report
    assert "Energy consumed       5.25 Wh" in report
    assert "HIGHEST-LOAD EVENT" in report
    assert "Voltage recovery      0.80 V" in report
    assert "COUNTER WARNINGS" in report
    assert report.index("1. TAKEOFF") < report.index("2. SUSTAINED_HIGH_THROTTLE")
    assert "   Context              AUTO" in report
    assert "   Capacity used before event    12.35 mAh" in report
    assert "   Margin to LOW        0.92 V" in report
    assert "CONFIGURATION WARNINGS" in report


def test_battery_formatter_preserves_optional_and_unavailable_values():
    analysis = _analysis(configuration=False, bounded=False)
    analysis.start_voltage = None
    analysis.load_event = None
    analysis.counter_warnings = []

    report = format_battery_report(
        Path("optional.BIN"), FlightWindow(0, 1_000_000), analysis
    )

    assert "Pack ID" not in report
    assert "Capacity         :" not in report
    assert "Start voltage         Unavailable" in report
    assert "No valid load event is available." in report
    assert "No bounded load events detected." in report


def test_battery_formatter_does_not_invent_missing_configuration_values():
    analysis = _analysis(bounded=False)
    analysis.session_configuration = SimpleNamespace(
        capacity_mah=None,
        low_voltage=0,
        critical_voltage=None,
        warnings=(),
    )

    report = format_battery_report(
        Path("configuration.bin"), FlightWindow(0, 1_000_000), analysis
    )

    assert "Capacity         : Unavailable" in report
    assert "Low voltage      : Disabled" in report
    assert "Critical voltage : Unavailable" in report


def test_battery_formatter_reports_unavailable_analysis():
    report = format_battery_report(
        Path("invalid.bin"), FlightWindow(1_000_000, 2_000_000), None
    )

    assert "Log    : invalid.bin" in report
    assert "Window : 00:01.000 -> 00:02.000" in report
    assert "No valid battery analysis is available." in report
    assert "Battery instance" not in report


def test_cli_print_report_uses_exact_shared_formatter(capsys):
    path = Path("selected.bin")
    window = FlightWindow(1_000_000, 66_400_000)
    analysis = _analysis()
    expected = format_battery_report(path, window, analysis, "Pack supplied")

    BatteryAnalysisPresentation(pack_id="Pack supplied")._print_report(
        path, window, analysis
    )

    assert capsys.readouterr().out == f"\n{expected}\n"
