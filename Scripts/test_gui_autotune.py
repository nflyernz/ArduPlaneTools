"""Focused tests for threaded GUI AUTOTUNE integration."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import gui.autotune_adapter as adapter_module
from core.log_reader import UnsupportedFirmwareError
from gui import ANALYSIS_TABS, MainWindow


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(adapter):
        window = MainWindow(autotune_adapter=adapter)
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._autotune_thread is not None:
            pytest.fail("test left an AUTOTUNE worker active")
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


def test_adapter_reuses_existing_autotune_pipeline(monkeypatch, tmp_path):
    selected = tmp_path / "pipeline.bin"
    config = object()
    flight_log = object()
    result = object()
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

    class _Detector:
        def detect(self, supplied_log):
            calls.append(("detect", supplied_log))
            return result

    def formatter(supplied_result, path):
        calls.append(("format", supplied_result, path))
        return "existing formatted report"

    monkeypatch.setattr(adapter_module, "Config", config_factory)
    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "AutotuneDetector", _Detector)
    monkeypatch.setattr(adapter_module, "format_autotune_report", formatter)

    assert adapter_module.analyse_autotune_log(selected) == "existing formatted report"
    assert calls == [
        ("config", "Config/autotune.yaml"),
        ("reader", selected, config),
        ("read",),
        ("detect", flight_log),
        ("format", result, selected),
    ]


def test_autotune_button_requires_existing_bin(make_window, tmp_path):
    window = make_window(lambda _path: "unused")
    assert not window.autotune_analyse_button.isEnabled()

    window.set_selected_log(tmp_path / "missing.bin")
    assert not window.autotune_analyse_button.isEnabled()
    window.start_autotune_analysis()
    assert "does not exist" in window.report_for("AUTOTUNE").toPlainText()

    wrong_type = tmp_path / "flight.csv"
    wrong_type.touch()
    window.set_selected_log(wrong_type)
    assert not window.autotune_analyse_button.isEnabled()
    window.start_autotune_analysis()
    assert "must have a .bin extension" in window.report_for(
        "AUTOTUNE"
    ).toPlainText()

    selected = _select_existing_bin(window, tmp_path, "valid.BIN")
    assert window.selected_log == selected
    assert window.autotune_analyse_button.isEnabled()


def test_success_runs_selected_path_once_in_background_and_restores_controls(
    qt_app,
    make_window,
    tmp_path,
):
    started = threading.Event()
    release = threading.Event()
    calls = []
    worker_threads = []
    main_thread = threading.get_ident()

    def adapter(path):
        calls.append(path)
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return f"AUTOTUNE Review\nLog: {path}\nFirmware: ArduPlane V4.7.1"

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)
    unaffected = {
        name: window.report_for(name).toPlainText()
        for name in ANALYSIS_TABS
        if name != "AUTOTUNE"
    }

    window.autotune_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._autotune_thread is not None
    assert not window.autotune_analyse_button.isEnabled()
    assert window.autotune_analyse_button.text() == "Analysing…"
    assert not window.choose_log_button.isEnabled()
    assert "no progress percentage" in window.report_for(
        "AUTOTUNE"
    ).toPlainText()

    window.start_autotune_analysis()
    window.show_analysis_tab("Landing")
    qt_app.processEvents()
    assert "AUTOTUNE analysis running" in window.statusBar().currentMessage()
    assert window.current_analysis == "Landing"
    assert calls == [selected]

    release.set()
    _wait_until(qt_app, lambda: window._autotune_thread is None)

    report = window.report_for("AUTOTUNE").toPlainText()
    assert f"Log: {selected}" in report
    assert "Firmware: ArduPlane V4.7.1" in report
    assert calls == [selected]
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != main_thread
    assert window.autotune_analyse_button.isEnabled()
    assert window.autotune_analyse_button.text() == "Analyse"
    assert window.choose_log_button.isEnabled()
    assert window._autotune_worker is None
    assert {
        name: window.report_for(name).toPlainText()
        for name in unaffected
    } == unaffected


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            UnsupportedFirmwareError("ArduCopter is unsupported"),
            "Unsupported firmware.\nArduCopter is unsupported",
        ),
        (OSError("cannot read BIN"), "Unable to read log: cannot read BIN"),
    ],
)
def test_known_failures_are_presented_and_controls_recover(
    qt_app,
    make_window,
    tmp_path,
    failure,
    expected,
):
    def adapter(_path):
        raise failure

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.autotune_analyse_button.click()
    _wait_until(qt_app, lambda: window._autotune_thread is None)

    assert expected in window.report_for("AUTOTUNE").toPlainText()
    assert expected.replace("\n", " — ") in window.statusBar().currentMessage()
    assert window.autotune_analyse_button.isEnabled()
    assert window.choose_log_button.isEnabled()
    assert window._autotune_worker is None


def test_successful_retry_replaces_unexpected_error(
    qt_app,
    make_window,
    tmp_path,
):
    attempts = []

    def adapter(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError("synthetic failure")
        return "AUTOTUNE Review\nSessions: 0"

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)

    window.autotune_analyse_button.click()
    _wait_until(qt_app, lambda: window._autotune_thread is None)
    assert "failed unexpectedly: synthetic failure" in window.report_for(
        "AUTOTUNE"
    ).toPlainText()

    window.autotune_analyse_button.click()
    _wait_until(qt_app, lambda: window._autotune_thread is None)
    assert window.report_for("AUTOTUNE").toPlainText() == (
        "AUTOTUNE Review\nSessions: 0"
    )
    assert "Error" not in window.report_for("AUTOTUNE").toPlainText()
    assert attempts == [selected, selected]


def test_close_waits_for_active_worker_and_then_closes(
    qt_app,
    make_window,
    tmp_path,
):
    started = threading.Event()
    release = threading.Event()

    def adapter(_path):
        started.set()
        assert release.wait(2)
        return "AUTOTUNE Review\nSessions: 0"

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.autotune_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window.close() is False
    assert window._close_after_worker
    assert window.isVisible()
    assert "Waiting for AUTOTUNE analysis" in window.statusBar().currentMessage()

    release.set()
    _wait_until(
        qt_app,
        lambda: window._autotune_thread is None and not window.isVisible(),
    )
    assert window._autotune_worker is None
