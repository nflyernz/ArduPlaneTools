"""Focused tests for threaded GUI Landing Analysis integration."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from core.log_reader import UnsupportedFirmwareError
from gui import MainWindow
import gui.landing_adapter as adapter_module


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(
        landing_adapter,
        autotune_adapter=lambda _path: "AUTOTUNE report",
        takeoff_adapter=lambda _path: "TAKEOFF report",
        stall_adapter=lambda _path: "Stall report",
    ):
        window = MainWindow(
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


def test_adapter_uses_config_reader_and_processes_every_flight_in_order(
    monkeypatch, tmp_path
):
    selected = tmp_path / "pipeline.BIN"
    config = object()
    flights = (object(), object(), object())
    flight_log = type("FlightLog", (), {"flights": flights})()
    results = []
    calls = []

    def config_factory(path):
        calls.append(("config", path))
        return config

    class _Reader:
        def __init__(self, path, config=None):
            calls.append(("reader", path, config))

        def read(self):
            calls.append(("read",))
            return flight_log

    class _Analysis:
        def __init__(self, config=None):
            calls.append(("analysis", config))

        def analyse(self, supplied_log, flight):
            result = object()
            calls.append(("analyse", supplied_log, flight))
            results.append(result)
            return result

    def formatter(path, supplied_results, count):
        calls.append(("format", path, tuple(supplied_results), count))
        return "existing Landing report"

    monkeypatch.setattr(adapter_module, "Config", config_factory)
    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "LandingAnalysis", _Analysis)
    monkeypatch.setattr(adapter_module, "format_landing_log_report", formatter)

    assert adapter_module.analyse_landing_log(selected) == "existing Landing report"
    assert calls == [
        ("config", "Config/landing.yaml"),
        ("reader", selected, config),
        ("read",),
        ("analysis", config),
        ("analyse", flight_log, flights[0]),
        ("analyse", flight_log, flights[1]),
        ("analyse", flight_log, flights[2]),
        ("format", selected, tuple(results), 3),
    ]


def test_adapter_reports_a_bin_with_no_detected_flights(monkeypatch, tmp_path):
    selected = tmp_path / "no-flights.bin"

    class _Reader:
        def __init__(self, path, config=None):
            assert path == selected
            assert config is not None

        @staticmethod
        def read():
            return type("FlightLog", (), {"flights": ()})()

    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)

    report = adapter_module.analyse_landing_log(selected)

    assert "[  1/1] no-flights.bin" in report
    assert "Loaded: 0 flight(s)\nNo flights detected." in report
    assert "Flight results              0" in report
    assert "No landing attempts detected." not in report


def test_landing_button_requires_existing_bin(make_window, tmp_path):
    window = make_window(lambda _path: "unused")
    assert not window.landing_analyse_button.isEnabled()

    window.set_selected_log(tmp_path / "missing.bin")
    assert not window.landing_analyse_button.isEnabled()
    window.start_landing_analysis()
    assert "does not exist" in window.report_for("Landing").toPlainText()

    selected = _select_existing_bin(window, tmp_path, "valid.BIN")
    assert window.selected_log == selected
    assert window.landing_analyse_button.isEnabled()


def test_landing_runs_responsively_and_excludes_other_analyses(
    qt_app, make_window, tmp_path
):
    started = threading.Event()
    release = threading.Event()
    landing_calls = []
    other_calls = []
    worker_threads = []
    main_thread = threading.get_ident()

    def landing_adapter(path):
        landing_calls.append(path)
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return "Landing Analysis\nNo landing attempts detected."

    def other_adapter(path):
        other_calls.append(path)
        return "unexpected"

    window = make_window(
        landing_adapter,
        autotune_adapter=other_adapter,
        takeoff_adapter=other_adapter,
        stall_adapter=other_adapter,
    )
    selected = _select_existing_bin(window, tmp_path)
    window.landing_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._active_analysis == "Landing"
    assert not window.landing_analyse_button.isEnabled()
    assert not window.autotune_analyse_button.isEnabled()
    assert not window.takeoff_analyse_button.isEnabled()
    assert not window.stall_analyse_button.isEnabled()
    assert window.landing_analyse_button.text() == "Analysing…"
    assert not window.choose_log_button.isEnabled()
    assert "no progress percentage" in window.report_for("Landing").toPlainText()

    window.start_landing_analysis()
    window.start_autotune_analysis()
    window.start_takeoff_analysis()
    window.start_stall_analysis()
    window.show_analysis_tab("AUTOTUNE")
    qt_app.processEvents()
    assert window.current_analysis == "AUTOTUNE"
    assert "Landing analysis running" in window.statusBar().currentMessage()
    assert landing_calls == [selected]
    assert other_calls == []

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert window.report_for("Landing").toPlainText() == (
        "Landing Analysis\nNo landing attempts detected."
    )
    assert worker_threads[0] != main_thread
    assert window.landing_analyse_button.isEnabled()
    assert window.autotune_analyse_button.isEnabled()
    assert window.takeoff_analyse_button.isEnabled()
    assert window.stall_analyse_button.isEnabled()
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
            "Landing analysis failed unexpectedly: synthetic failure",
        ),
    ),
)
def test_landing_failures_recover_and_successful_retry_replaces_error(
    qt_app, make_window, tmp_path, failure, expected
):
    attempts = []

    def adapter(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise failure
        return "Landing Analysis\nNo landing attempts detected."

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)

    window.landing_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert expected in window.report_for("Landing").toPlainText()
    assert window.landing_analyse_button.isEnabled()

    window.landing_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.report_for("Landing").toPlainText() == (
        "Landing Analysis\nNo landing attempts detected."
    )
    assert "Error" not in window.report_for("Landing").toPlainText()
    assert attempts == [selected, selected]


def test_close_waits_for_active_landing_worker(qt_app, make_window, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def adapter(_path):
        started.set()
        assert release.wait(2)
        return "Landing Analysis\nNo landing attempts detected."

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.landing_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window.close() is False
    assert window._close_after_worker
    assert window.isVisible()
    assert "Waiting for Landing analysis" in window.statusBar().currentMessage()

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    _wait_until(qt_app, lambda: not window.isVisible())


def test_overview_marks_landing_connected_and_navigates(qt_app, make_window):
    window = make_window(lambda _path: "unused")

    assert "Connected to the GUI" in window.overview_buttons[
        "Landing"
    ].description()
    window.overview_buttons["Landing"].click()
    qt_app.processEvents()

    assert window.current_analysis == "Landing"
    assert "Reports use the existing Landing evidence pipeline" in window.report_for(
        "Landing"
    ).toPlainText()
    assert "ready" in window.statusBar().currentMessage()
