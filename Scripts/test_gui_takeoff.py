"""Focused tests for threaded GUI TAKEOFF integration."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import gui.takeoff_adapter as adapter_module
from core.log_reader import UnsupportedFirmwareError
from gui import MainWindow


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(takeoff_adapter, autotune_adapter=lambda _path: "AUTOTUNE report"):
        window = MainWindow(
            autotune_adapter=autotune_adapter,
            takeoff_adapter=takeoff_adapter,
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


def test_adapter_loads_bin_and_calls_shared_takeoff_analysis(monkeypatch, tmp_path):
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

    def analyse(supplied_log, path):
        calls.append(("analyse", supplied_log, path))
        return "existing TAKEOFF report"

    monkeypatch.setattr(adapter_module, "Config", config_factory)
    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "analyse_takeoff_flight_log", analyse)

    assert adapter_module.analyse_takeoff_log(selected) == "existing TAKEOFF report"
    assert calls == [
        ("config", "Config/landing.yaml"),
        ("reader", selected, config),
        ("read",),
        ("analyse", flight_log, selected),
    ]


def test_takeoff_button_requires_existing_bin(make_window, tmp_path):
    window = make_window(lambda _path: "unused")
    assert not window.takeoff_analyse_button.isEnabled()

    window.set_selected_log(tmp_path / "missing.bin")
    assert not window.takeoff_analyse_button.isEnabled()
    window.start_takeoff_analysis()
    assert "does not exist" in window.report_for("TAKEOFF").toPlainText()

    wrong_type = tmp_path / "flight.csv"
    wrong_type.touch()
    window.set_selected_log(wrong_type)
    assert not window.takeoff_analyse_button.isEnabled()
    window.start_takeoff_analysis()
    assert "must have a .bin extension" in window.report_for(
        "TAKEOFF"
    ).toPlainText()

    selected = _select_existing_bin(window, tmp_path, "valid.BIN")
    assert window.selected_log == selected
    assert window.takeoff_analyse_button.isEnabled()


def test_takeoff_runs_selected_path_once_and_blocks_other_analysis(
    qt_app,
    make_window,
    tmp_path,
):
    started = threading.Event()
    release = threading.Event()
    takeoff_calls = []
    autotune_calls = []
    worker_threads = []
    main_thread = threading.get_ident()

    def takeoff_adapter(path):
        takeoff_calls.append(path)
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return f"TAKEOFF Analysis\nLog: {path}\nNo TAKEOFF-mode executions found."

    def autotune_adapter(path):
        autotune_calls.append(path)
        return "AUTOTUNE report"

    window = make_window(takeoff_adapter, autotune_adapter)
    selected = _select_existing_bin(window, tmp_path)
    autotune_before = window.report_for("AUTOTUNE").toPlainText()

    window.takeoff_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._active_analysis == "TAKEOFF"
    assert not window.takeoff_analyse_button.isEnabled()
    assert not window.autotune_analyse_button.isEnabled()
    assert window.takeoff_analyse_button.text() == "Analysing…"
    assert not window.choose_log_button.isEnabled()
    assert "no progress percentage" in window.report_for("TAKEOFF").toPlainText()

    window.start_takeoff_analysis()
    window.start_autotune_analysis()
    window.show_analysis_tab("AUTOTUNE")
    qt_app.processEvents()
    assert window.current_analysis == "AUTOTUNE"
    assert "TAKEOFF analysis running" in window.statusBar().currentMessage()
    assert takeoff_calls == [selected]
    assert autotune_calls == []

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert window.report_for("TAKEOFF").toPlainText() == (
        f"TAKEOFF Analysis\nLog: {selected}\nNo TAKEOFF-mode executions found."
    )
    assert window.report_for("AUTOTUNE").toPlainText() == autotune_before
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != main_thread
    assert window.takeoff_analyse_button.isEnabled()
    assert window.autotune_analyse_button.isEnabled()
    assert window.choose_log_button.isEnabled()
    assert window._analysis_worker is None


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
            "TAKEOFF analysis failed unexpectedly: synthetic failure",
        ),
    ),
)
def test_takeoff_failures_recover_and_successful_retry_replaces_error(
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
        return "TAKEOFF Analysis\nNo TAKEOFF-mode executions found."

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)

    window.takeoff_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert expected in window.report_for("TAKEOFF").toPlainText()
    assert expected.replace("\n", " — ") in window.statusBar().currentMessage()
    assert window.takeoff_analyse_button.isEnabled()

    window.takeoff_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.report_for("TAKEOFF").toPlainText() == (
        "TAKEOFF Analysis\nNo TAKEOFF-mode executions found."
    )
    assert "Error" not in window.report_for("TAKEOFF").toPlainText()
    assert attempts == [selected, selected]


def test_close_waits_for_active_takeoff_worker(qt_app, make_window, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def adapter(_path):
        started.set()
        assert release.wait(2)
        return "TAKEOFF Analysis\nNo TAKEOFF-mode executions found."

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.takeoff_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window.close() is False
    assert window._close_after_worker
    assert window.isVisible()
    assert "Waiting for TAKEOFF analysis" in window.statusBar().currentMessage()

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    _wait_until(qt_app, lambda: not window.isVisible())
