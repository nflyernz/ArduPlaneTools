"""Regression tests for reusable Event Timeline text presentation."""

from pathlib import Path

from analyses.event_timeline import EventTimelineAnalysis, format_event_timeline
from core.events import EventType, TimelineEvent
from core.flight_window import FlightWindow


def test_event_formatter_preserves_exact_existing_presentation():
    log_path = Path("flight.bin")
    window = FlightWindow(start_us=1_000_000, end_us=65_250_000)
    events = [
        TimelineEvent(2_000_000, EventType.MSG, "Takeoff detected"),
        TimelineEvent(3_500_000, EventType.MODE, "FBWA"),
        TimelineEvent(4_000_000, EventType.LAND_STAGE, "2 (fh=1.20, slope=0.030)"),
    ]

    report = format_event_timeline(log_path, window, events)

    assert report == "\n".join(
        (
            "Event Timeline",
            "=" * 70,
            "Log    : flight.bin",
            "Window : 00:01.000 -> 01:05.250",
            "Events : 3",
            "",
            "00:02.000  MSG           Takeoff detected",
            "00:03.500  MODE          FBWA",
            "00:04.000  LAND_STAGE    2 (fh=1.20, slope=0.030)",
        )
    )


def test_event_formatter_reports_empty_supported_event_set():
    report = format_event_timeline(
        Path("quiet.BIN"),
        FlightWindow(start_us=10_000_000, end_us=20_000_000),
        [],
    )

    assert "Log    : quiet.BIN" in report
    assert "Window : 00:10.000 -> 00:20.000" in report
    assert "Events : 0\n\nNo events found." in report


def test_cli_print_timeline_uses_exact_shared_formatter(capsys):
    path = Path("selected.bin")
    window = FlightWindow(start_us=1_000_000, end_us=2_000_000)
    events = [TimelineEvent(1_500_000, EventType.MODE, "MANUAL")]
    expected = format_event_timeline(path, window, events)

    EventTimelineAnalysis()._print_timeline(path, window, events)

    assert capsys.readouterr().out == f"\n{expected}\n"
