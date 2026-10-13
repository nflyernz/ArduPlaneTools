"""Focused tests for aircraft-BIN Radio Link GUI integration."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton

import analyses.radio_link as presentation
from core.log_reader import UnsupportedFirmwareError
from core.radio_link import RadioLinkDetector
from gui import MainWindow
import gui.radio_link_adapter as adapter_module
from gui.pack_management_adapter import BatteryPackManagementService
from gui.pack_performance_adapter import BatteryPackPerformanceService
from gui.radio_link_adapter import RadioLinkGuiResult
from test_radio_link import _log, arm, rc


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def _select_bin(window, tmp_path, name="radio.bin"):
    path = tmp_path / name
    path.touch()
    window.set_selected_log(path)
    return path.resolve()


@pytest.fixture
def make_window(qt_app, tmp_path):
    windows = []

    def create(radio_link_adapter, **adapters):
        window = MainWindow(
            radio_link_adapter=radio_link_adapter,
            pack_management_service=BatteryPackManagementService(
                pack_store_path=tmp_path / "packs.json",
                history_store_path=tmp_path / "history.json",
            ),
            pack_performance_service=BatteryPackPerformanceService(
                pack_store_path=tmp_path / "packs.json",
                history_store_path=tmp_path / "history.json",
            ),
            **adapters,
        )
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a Radio Link worker active")
        window.close()
    qt_app.processEvents()


def test_adapter_reads_detects_once_and_uses_both_existing_formatters(
    monkeypatch, tmp_path
):
    selected = tmp_path / "source.BIN"
    config = object()
    flight_log = object()
    detection = object()
    calls = []

    monkeypatch.setattr(
        adapter_module,
        "Config",
        lambda path: calls.append(("config", path)) or config,
    )

    class Reader:
        def __init__(self, path, config=None):
            calls.append(("reader", path, config))

        def read(self):
            calls.append(("read",))
            return flight_log

    class Detector:
        def detect(self, supplied_log):
            calls.append(("detect", supplied_log))
            return detection

    monkeypatch.setattr(adapter_module, "FlightReader", Reader)
    monkeypatch.setattr(adapter_module, "RadioLinkDetector", Detector)
    monkeypatch.setattr(
        adapter_module,
        "format_radio_link_summary",
        lambda result, path, log: calls.append(
            ("summary", result, path, log)
        )
        or "existing summary",
    )
    monkeypatch.setattr(
        adapter_module,
        "format_radio_link_report",
        lambda result, path: calls.append(("detail", result, path))
        or "existing detail",
    )

    result = adapter_module.analyse_radio_link_log(selected)
    resolved = selected.resolve()

    assert result == RadioLinkGuiResult(
        resolved,
        "existing summary",
        "existing detail",
    )
    assert calls == [
        ("config", "Config/radio_link.yaml"),
        ("reader", resolved, config),
        ("read",),
        ("detect", flight_log),
        ("summary", detection, resolved, flight_log),
        ("detail", detection, resolved),
    ]


@pytest.mark.parametrize(
    ("flight_log", "summary_text", "detail_text"),
    [
        (
            _log(rc(1_000_000, 1)),
            "No confirmed armed RC-input loss",
            "No armed Plane RC-failsafe evidence found",
        ),
        (
            _log(rc(1_000_000, 1), rc(2_000_000, 2), end=3_000_000),
            "unknown armed state: 1",
            "Input-invalid episode open at log boundary",
        ),
        (
            _log(
                arm(500_000, 1),
                rc(1_000_000, 1),
                rc(2_000_000, 2),
                end=3_000_000,
            ),
            "1 confirmed armed",
            "Armed state: armed at start",
        ),
    ],
)
def test_adapter_preserves_zero_unknown_armed_and_incomplete_evidence(
    monkeypatch,
    tmp_path,
    flight_log,
    summary_text,
    detail_text,
):
    selected = tmp_path / "evidence.bin"

    class Reader:
        def __init__(self, path, config=None):
            assert path == selected.resolve()

        def read(self):
            return flight_log

    monkeypatch.setattr(adapter_module, "FlightReader", Reader)
    result = adapter_module.analyse_radio_link_log(selected)
    detected = RadioLinkDetector().detect(flight_log)

    assert result.summary == presentation.format_radio_link_summary(
        detected,
        selected.resolve(),
        flight_log,
    )
    assert result.detail == presentation.format_radio_link_report(
        detected,
        selected.resolve(),
    )
    assert summary_text in result.summary
    assert detail_text in result.detail


def test_bin_is_required_and_radio_button_dispatches_only_radio_link(
    qt_app, tmp_path, make_window
):
    radio_calls = []
    stall_calls = []

    def radio_adapter(path):
        radio_calls.append(path)
        return RadioLinkGuiResult(path, "summary", "detail")

    window = make_window(
        radio_adapter,
        stall_adapter=lambda path: stall_calls.append(path) or "stall",
    )
    window.show_analysis_tab("Radio Link")
    widget = window._radio_link.widget

    assert not widget.analyse_button.isEnabled()
    window._radio_link.request_analysis()
    assert "Select a BIN log" in widget.report.toPlainText()

    selected = _select_bin(window, tmp_path)
    assert widget.analyse_button.isEnabled()
    widget.analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert radio_calls == [selected]
    assert stall_calls == []
    assert widget.report.toPlainText() == "summary"
    assert "Connected to the GUI" in window.overview_buttons[
        "Radio Link"
    ].description()
    page = window.analysis_tabs.currentWidget()
    assert len(
        [
            button
            for button in page.findChildren(QPushButton)
            if button.text() == "Analyse"
        ]
    ) == 1
    assert "EdgeTX CSV" in widget.bin_only_notice.text()


def test_nonexistent_selected_source_is_rejected_before_dispatch(
    qt_app, tmp_path, make_window
):
    calls = []
    window = make_window(lambda path: calls.append(path))
    widget = window._radio_link.widget
    missing = tmp_path / "missing.bin"
    window.set_selected_log(missing)

    assert not widget.analyse_button.isEnabled()
    window._radio_link.request_analysis()

    assert calls == []
    assert "does not exist" in widget.report.toPlainText()


def test_summary_detail_switching_reuses_one_detector_result(
    qt_app, tmp_path, make_window
):
    calls = []

    def adapter(path):
        calls.append(path)
        return RadioLinkGuiResult(
            path,
            "Radio Link summary\nRC-input loss episodes: 1 confirmed armed",
            "Radio Link detail\n── Episode #1 — Aircraft BIN ──",
        )

    window = make_window(adapter)
    widget = window._radio_link.widget
    selected = _select_bin(window, tmp_path)
    widget.analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.report.toPlainText().startswith("Radio Link summary")
    assert not widget.summary_button.isEnabled()
    assert widget.detail_button.isEnabled()

    widget.detail_button.click()
    assert "Episode #1" in widget.report.toPlainText()
    widget.summary_button.click()
    assert widget.report.toPlainText().startswith("Radio Link summary")
    assert calls == [selected]


def test_new_source_invalidates_cached_result_without_rerun(
    qt_app, tmp_path, make_window
):
    calls = []

    def adapter(path):
        calls.append(path)
        return RadioLinkGuiResult(path, "summary", "detail")

    window = make_window(adapter)
    widget = window._radio_link.widget
    first = _select_bin(window, tmp_path, "first.bin")
    widget.analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.result.source_path == first

    second = _select_bin(window, tmp_path, "second.bin")

    assert widget.result is None
    assert "selected BIN changed" in widget.report.toPlainText()
    assert not widget.detail_button.isEnabled()
    assert widget.analyse_button.isEnabled()
    assert calls == [first]
    assert window.selected_log == second


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            UnsupportedFirmwareError("ArduCopter is unsupported"),
            "Unsupported firmware.\nArduCopter is unsupported",
        ),
        (OSError("malformed BIN"), "Unable to read log: malformed BIN"),
        (
            RuntimeError("detector failed"),
            "Radio Link analysis failed unexpectedly: detector failed",
        ),
    ],
)
def test_failures_recover_and_successful_retry_replaces_error(
    qt_app, tmp_path, make_window, failure, expected
):
    attempts = []

    def adapter(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise failure
        return RadioLinkGuiResult(path, "recovered summary", "recovered detail")

    window = make_window(adapter)
    widget = window._radio_link.widget
    selected = _select_bin(window, tmp_path)

    widget.analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert expected in widget.report.toPlainText()
    assert widget.analyse_button.isEnabled()

    widget.analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.report.toPlainText() == "recovered summary"
    assert attempts == [selected, selected]


def test_radio_worker_blocks_other_actions_and_pack_persistence(
    qt_app, tmp_path, make_window
):
    started = threading.Event()
    release = threading.Event()
    autotune_calls = []

    def adapter(path):
        started.set()
        assert release.wait(2)
        return RadioLinkGuiResult(path, "summary", "detail")

    window = make_window(
        adapter,
        autotune_adapter=lambda path: autotune_calls.append(path) or "autotune",
    )
    widget = window._radio_link.widget
    _select_bin(window, tmp_path)
    widget.analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert not window.autotune_analyse_button.isEnabled()
    assert not window.choose_log_button.isEnabled()
    assert not window._pack_performance.widget.refresh_button.isEnabled()
    window.start_autotune_analysis()
    assert autotune_calls == []
    assert not (tmp_path / "packs.json").exists()
    assert not (tmp_path / "history.json").exists()

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.autotune_analyse_button.isEnabled()


def test_source_change_during_worker_withholds_stale_result(
    qt_app, tmp_path, make_window
):
    started = threading.Event()
    release = threading.Event()

    def adapter(path):
        started.set()
        assert release.wait(2)
        return RadioLinkGuiResult(path, "old summary", "old detail")

    window = make_window(adapter)
    widget = window._radio_link.widget
    _select_bin(window, tmp_path, "old.bin")
    widget.analyse_button.click()
    assert started.wait(1)
    replacement = _select_bin(window, tmp_path, "new.bin")

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.result is None
    assert "previous result was not displayed" in widget.report.toPlainText()
    assert window.selected_log == replacement


def test_close_waits_for_active_radio_link_worker(qt_app, tmp_path, make_window):
    started = threading.Event()
    release = threading.Event()

    def adapter(path):
        started.set()
        assert release.wait(2)
        return RadioLinkGuiResult(path, "summary", "detail")

    window = make_window(adapter)
    widget = window._radio_link.widget
    _select_bin(window, tmp_path)
    widget.analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    window.close()
    assert window.isVisible()
    release.set()
    _wait_until(
        qt_app,
        lambda: window._analysis_thread is None and not window.isVisible(),
    )
