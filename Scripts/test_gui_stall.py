"""Focused tests for threaded GUI Stall Analysis integration."""

import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from analyses.stall import analyse_stall_flight_log
import gui.stall_adapter as adapter_module
from core.config import Config
from core.log_reader import UnsupportedFirmwareError
from gui import ANALYSIS_TABS, MainWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(
        stall_adapter,
        autotune_adapter=lambda _path: "AUTOTUNE report",
        takeoff_adapter=lambda _path: "TAKEOFF report",
    ):
        window = MainWindow(
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


def test_adapter_uses_stall_config_reader_and_shared_analysis(monkeypatch, tmp_path):
    selected = tmp_path / "pipeline.BIN"
    config = object()
    flight_log = object()
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

    def analyse(supplied_log, supplied_config):
        calls.append(("analyse", supplied_log, supplied_config))
        return "existing Stall report"

    monkeypatch.setattr(adapter_module, "Config", config_factory)
    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "analyse_stall_flight_log", analyse)

    assert adapter_module.analyse_stall_log(selected) == "existing Stall report"
    assert calls == [
        ("config", "Config/stall_test.yaml"),
        ("reader", selected, config),
        ("read",),
        ("analyse", flight_log, config),
    ]


def test_shared_stall_analysis_preserves_no_flight_window_report():
    report = analyse_stall_flight_log(
        SimpleNamespace(flights=()),
        Config("Config/stall_test.yaml"),
    )

    assert "Stall Analysis | FBWA slow-flight evidence" in report
    assert "No detected flight windows to analyse." in report


def test_stall_runs_responsively_and_excludes_other_analyses(
    qt_app,
    make_window,
    tmp_path,
):
    started = threading.Event()
    release = threading.Event()
    stall_calls = []
    autotune_calls = []
    takeoff_calls = []
    worker_threads = []
    main_thread = threading.get_ident()

    def stall_adapter(path):
        stall_calls.append(path)
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return (
            "Stall Analysis | FBWA slow-flight evidence\n"
            "No detected flight windows to analyse."
        )

    def autotune_adapter(path):
        autotune_calls.append(path)
        return "AUTOTUNE report"

    def takeoff_adapter(path):
        takeoff_calls.append(path)
        return "TAKEOFF report"

    window = make_window(stall_adapter, autotune_adapter, takeoff_adapter)
    selected = _select_existing_bin(window, tmp_path, "selected.BIN")
    assert window.stall_analyse_button.isEnabled()

    window.stall_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._active_analysis == "Stall"
    assert not window.stall_analyse_button.isEnabled()
    assert not window.autotune_analyse_button.isEnabled()
    assert not window.takeoff_analyse_button.isEnabled()
    assert window.stall_analyse_button.text() == "Analysing…"
    assert not window.choose_log_button.isEnabled()
    assert "no progress percentage" in window.report_for("Stall").toPlainText()

    window.start_stall_analysis()
    window.start_autotune_analysis()
    window.start_takeoff_analysis()
    window.analysis_tabs.setCurrentIndex(ANALYSIS_TABS.index("TAKEOFF"))
    qt_app.processEvents()
    assert window.current_analysis == "TAKEOFF"
    assert "Stall analysis running" in window.statusBar().currentMessage()
    assert stall_calls == [selected]
    assert autotune_calls == []
    assert takeoff_calls == []

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    report = window.report_for("Stall").toPlainText()
    assert "Stall Analysis | FBWA slow-flight evidence" in report
    assert "No detected flight windows to analyse." in report
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != main_thread
    assert window.stall_analyse_button.isEnabled()
    assert window.autotune_analyse_button.isEnabled()
    assert window.takeoff_analyse_button.isEnabled()
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
            "Stall analysis failed unexpectedly: synthetic failure",
        ),
    ),
)
def test_stall_failures_recover_and_successful_retry_replaces_error(
    qt_app,
    make_window,
    tmp_path,
    failure,
    expected,
):
    attempts = []

    def adapter(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise failure
        return (
            "Stall Analysis | FBWA slow-flight evidence\n"
            "No detected flight windows to analyse."
        )

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)

    window.stall_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert expected in window.report_for("Stall").toPlainText()
    assert expected.replace("\n", " — ") in window.statusBar().currentMessage()
    assert window.stall_analyse_button.isEnabled()

    window.stall_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "No detected flight windows" in window.report_for(
        "Stall"
    ).toPlainText()
    assert "Error" not in window.report_for("Stall").toPlainText()
    assert attempts == [selected, selected]


def test_close_waits_for_active_stall_worker(qt_app, make_window, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def adapter(_path):
        started.set()
        assert release.wait(2)
        return "Stall Analysis | FBWA slow-flight evidence"

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.stall_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window.close() is False
    assert window._close_after_worker
    assert window.isVisible()
    assert "Waiting for Stall analysis" in window.statusBar().currentMessage()

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    _wait_until(qt_app, lambda: not window.isVisible())
