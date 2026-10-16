"""Focused tests for threaded GUI Event Timeline integration."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from core.events import EventType, TimelineEvent
from core.flight_window import FlightWindow
from core.log_reader import UnsupportedFirmwareError
from gui import MainWindow
import gui.events_adapter as adapter_module


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(
        events_adapter,
        landing_adapter=lambda _path: "Landing report",
        autotune_adapter=lambda _path: "AUTOTUNE report",
        takeoff_adapter=lambda _path: "TAKEOFF report",
        stall_adapter=lambda _path: "Stall report",
    ):
        window = MainWindow(
            events_adapter=events_adapter,
            landing_adapter=landing_adapter,
            autotune_adapter=autotune_adapter,
            takeoff_adapter=takeoff_adapter,
            stall_adapter=stall_adapter,
        )
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left an analysis worker active")
        window.close()
    qt_app.processEvents()


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def _select_existing_bin(window, tmp_path, name="flight.bin"):
    selected = tmp_path / name
    selected.touch()
    window.set_selected_log(selected)
    return selected.resolve()


def test_adapter_loads_bin_and_extracts_each_flight_in_order(monkeypatch, tmp_path):
    selected = tmp_path / "pipeline.BIN"
    flights = (
        FlightWindow(1_000_000, 2_000_000),
        FlightWindow(3_000_000, 4_000_000),
    )
    flight_log = type("FlightLog", (), {"flights": flights})()
    calls = []

    class _Reader:
        def __init__(self, path):
            calls.append(("reader", path))

        def read(self):
            calls.append(("read",))
            return flight_log

    class _Extractor:
        def extract(self, supplied_log, window):
            calls.append(("extract", supplied_log, window))
            return [object()] if window is flights[0] else [object(), object()]

    def formatter(path, window, events):
        calls.append(("format", path, window, len(events)))
        return f"timeline-{window.start_us}-{len(events)}"

    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "EventExtractor", _Extractor)
    monkeypatch.setattr(adapter_module, "format_event_timeline", formatter)

    report = adapter_module.analyse_events_log(selected)

    assert report.index("FLIGHT 1") < report.index("timeline-1000000-1")
    assert report.index("timeline-1000000-1") < report.index("FLIGHT 2")
    assert report.index("FLIGHT 2") < report.index("timeline-3000000-2")
    assert calls == [
        ("reader", selected),
        ("read",),
        ("extract", flight_log, flights[0]),
        ("format", selected, flights[0], 1),
        ("extract", flight_log, flights[1]),
        ("format", selected, flights[1], 2),
    ]


def test_adapter_keeps_multiple_real_timelines_separate(monkeypatch, tmp_path):
    selected = tmp_path / "multiple.bin"
    flights = (
        FlightWindow(1_000_000, 2_000_000),
        FlightWindow(10_000_000, 12_000_000),
    )
    flight_log = type("FlightLog", (), {"flights": flights})()

    class _Reader:
        def __init__(self, path):
            assert path == selected

        @staticmethod
        def read():
            return flight_log

    class _Extractor:
        @staticmethod
        def extract(_flight_log, window):
            if window is flights[0]:
                return []
            return [TimelineEvent(11_000_000, EventType.MODE, "FBWA")]

    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "EventExtractor", _Extractor)

    report = adapter_module.analyse_events_log(selected)

    assert report.count("Event Timeline") == 2
    assert report.count("Log    : multiple.bin") == 2
    assert "FLIGHT 1" in report and "Events : 0\n\nNo events found." in report
    assert "FLIGHT 2" in report and "Events : 1" in report
    assert "00:11.000  MODE          FBWA" in report
    assert report.index("FLIGHT 1") < report.index("FLIGHT 2")


def test_adapter_reports_bin_with_no_detected_flights(monkeypatch, tmp_path):
    selected = tmp_path / "no-flights.bin"

    class _Reader:
        def __init__(self, path):
            assert path == selected

        @staticmethod
        def read():
            return type("FlightLog", (), {"flights": ()})()

    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)

    report = adapter_module.analyse_events_log(selected)

    assert "Log     : no-flights.bin" in report
    assert "Flights : 0" in report
    assert "No flights found." in report
    assert "No events found." not in report


def test_events_button_requires_existing_bin(make_window, tmp_path):
    window = make_window(lambda _path: "unused")
    assert not window.events_analyse_button.isEnabled()

    window.set_selected_log(tmp_path / "missing.bin")
    assert not window.events_analyse_button.isEnabled()
    window.start_events_analysis()
    assert "does not exist" in window.report_for("Events").toPlainText()

    selected = _select_existing_bin(window, tmp_path, "valid.BIN")
    assert window.selected_log == selected
    assert window.events_analyse_button.isEnabled()


def test_events_runs_responsively_and_excludes_other_analyses(
    qt_app, make_window, tmp_path
):
    started = threading.Event()
    release = threading.Event()
    event_calls = []
    other_calls = []
    worker_threads = []
    main_thread = threading.get_ident()

    def events_adapter(path):
        event_calls.append(path)
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return "Event Timeline\nEvents : 0\n\nNo events found."

    def other_adapter(path):
        other_calls.append(path)
        return "unexpected"

    window = make_window(
        events_adapter,
        landing_adapter=other_adapter,
        autotune_adapter=other_adapter,
        takeoff_adapter=other_adapter,
        stall_adapter=other_adapter,
    )
    selected = _select_existing_bin(window, tmp_path)
    window.events_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._active_analysis == "Events"
    for button in (
        window.events_analyse_button,
        window.landing_analyse_button,
        window.autotune_analyse_button,
        window.takeoff_analyse_button,
        window.stall_analyse_button,
    ):
        assert not button.isEnabled()
    assert window.events_analyse_button.text() == "Analysing…"
    assert not window.choose_log_button.isEnabled()

    window.start_events_analysis()
    window.start_landing_analysis()
    window.start_autotune_analysis()
    window.start_takeoff_analysis()
    window.start_stall_analysis()
    window.show_analysis_tab("Landing")
    qt_app.processEvents()
    assert window.current_analysis == "Landing"
    assert "Events analysis running" in window.statusBar().currentMessage()
    assert event_calls == [selected]
    assert other_calls == []

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "No events found." in window.report_for("Events").toPlainText()
    assert worker_threads[0] != main_thread
    for button in (
        window.events_analyse_button,
        window.landing_analyse_button,
        window.autotune_analyse_button,
        window.takeoff_analyse_button,
        window.stall_analyse_button,
    ):
        assert button.isEnabled()
    assert window.choose_log_button.isEnabled()


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (
            UnsupportedFirmwareError("ArduCopter is unsupported"),
            "Unsupported firmware.\nArduCopter is unsupported",
        ),
        (OSError("cannot read BIN"), "Unable to read log: cannot read BIN"),
        (
            RuntimeError("synthetic failure"),
            "Events analysis failed unexpectedly: synthetic failure",
        ),
    ),
)
def test_events_failures_recover_and_successful_retry_replaces_error(
    qt_app, make_window, tmp_path, failure, expected
):
    attempts = []

    def adapter(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise failure
        return "Event Timeline\nEvents : 0\n\nNo events found."

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)

    window.events_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert expected in window.report_for("Events").toPlainText()
    assert window.events_analyse_button.isEnabled()

    window.events_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "No events found." in window.report_for("Events").toPlainText()
    assert "Error" not in window.report_for("Events").toPlainText()
    assert attempts == [selected, selected]


def test_close_waits_for_active_events_worker(qt_app, make_window, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def adapter(_path):
        started.set()
        assert release.wait(2)
        return "Event Timeline"

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.events_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window.close() is False
    assert window._close_after_worker
    assert window.isVisible()
    assert "Waiting for Events analysis" in window.statusBar().currentMessage()

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    _wait_until(qt_app, lambda: not window.isVisible())


def test_overview_describes_events_and_navigates(qt_app, make_window):
    window = make_window(lambda _path: "unused")

    assert window.overview_buttons[
        "Events"
    ].description() == "Inspect the chronological flight event timeline."
    window.overview_buttons["Events"].click()
    qt_app.processEvents()

    assert window.current_analysis == "Events"
    assert window.report_for("Events").toPlainText() == "No analysis run yet."
    assert "ready" in window.statusBar().currentMessage()
