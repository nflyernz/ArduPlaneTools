"""Portable adapter and GUI tests for Range-Walk CSV marker preview."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog, QPushButton

from gui import MainWindow
from gui.pack_management_adapter import BatteryPackManagementService
from gui.pack_performance_adapter import BatteryPackPerformanceService
from gui.range_walk_adapter import (
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    analyse_range_walk_preview,
)
from test_range_walk import BASE, HEADER, _session


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def _request(path, down="1024", neutral="0", near_down="", request_id=1):
    return RangeWalkPreviewRequest(
        Path(path), down, neutral, near_down, request_id
    )


def _result(request, text="preview result"):
    return RangeWalkPreviewResult(
        request.source_path.resolve(),
        request.request_id,
        BASE,
        BASE,
        1,
        (),
        text,
    )


@pytest.fixture
def make_window(qt_app, tmp_path):
    windows = []

    def create(adapter=None, **adapters):
        window = MainWindow(
            range_walk_adapter=adapter,
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
        window.show_analysis_tab("Range-Walk Comparison")
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a Range-Walk worker active")
        window.close()
    qt_app.processEvents()


@pytest.mark.parametrize(("down", "near_down"), (("1024", ""), ("-1024", "-900")))
def test_adapter_detects_positive_and_negative_calibrated_holds(
    tmp_path, down, near_down
):
    session = _session(tmp_path, down=float(down))

    result = analyse_range_walk_preview(
        _request(session.path, down=down, near_down=near_down)
    )

    assert result.source_path == session.path.resolve()
    assert result.row_count == len(session.rows)
    assert result.recording_start == session.rows[0].clock
    assert result.recording_end == session.rows[-1].clock
    assert len(result.markers) == 5
    assert "Marker candidates: 5" in result.text
    assert "not confirmed physical landmarks" in result.text
    assert "CSV/marker preview only — comparison not yet connected" in result.text
    assert "hold 2.000 s" in result.text


def test_adapter_reports_extra_and_missing_candidates_without_inference(tmp_path):
    extra = _session(tmp_path, name="extra.csv", extra=(23,))
    missing = _session(tmp_path, name="missing.csv", holds=(2, 8, 14))

    extra_result = analyse_range_walk_preview(_request(extra.path))
    missing_result = analyse_range_walk_preview(_request(missing.path))

    assert len(extra_result.markers) == 6
    assert "Marker candidates: 6" in extra_result.text
    assert len(missing_result.markers) == 3
    assert "Marker candidates: 3" in missing_result.text
    assert "No baseline, landmark mapping, RF comparison" in missing_result.text


@pytest.mark.parametrize(
    ("down", "neutral", "near_down", "message"),
    (
        ("", "0", "", "Full elevator-down Ele is required"),
        ("down", "0", "", "Full elevator-down Ele must be numeric"),
        ("0", "0", "", "must differ from neutral"),
        ("1024", "0", "-1", "must lie between neutral and down"),
    ),
)
def test_adapter_rejects_missing_or_invalid_calibration(
    tmp_path, down, neutral, near_down, message
):
    session = _session(tmp_path)

    with pytest.raises(ValueError, match=message):
        analyse_range_walk_preview(
            _request(session.path, down, neutral, near_down)
        )


def test_adapter_uses_existing_missing_ele_validation(tmp_path):
    session = _session(
        tmp_path,
        name="missing_ele.csv",
        header=[field for field in HEADER if field != "Ele"],
    )

    with pytest.raises(ValueError, match="one numeric Ele"):
        analyse_range_walk_preview(_request(session.path))


def test_choose_csv_and_detect_without_shared_bin(
    qt_app, tmp_path, make_window, monkeypatch
):
    session = _session(tmp_path)
    dialog = {}

    def choose(*args):
        dialog["args"] = args
        return str(session.path), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose)
    window = make_window()
    widget = window._range_walk.widget

    assert window.selected_log is None
    assert not widget.detect_button.isEnabled()
    widget.choose_button.click()
    widget.down_edit.setText("1024")
    widget.neutral_edit.setText("0")
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    report = widget.report.toPlainText()
    assert widget.source_path == session.path.resolve()
    assert dialog["args"][3] == "EdgeTX CSV files (*.csv *.CSV)"
    assert session.path.name in report
    assert str(session.path.resolve()) in report
    assert "CSV rows: 330" in report
    assert "Marker candidates: 5" in report
    assert "onset 15:00:02.000" in report
    assert window.selected_log is None


def test_source_change_clears_old_result_and_withholds_stale_worker_output(
    qt_app, tmp_path, make_window
):
    first = _session(tmp_path, name="first.csv").path.resolve()
    second = _session(tmp_path, name="second.csv").path.resolve()
    started = threading.Event()
    release = threading.Event()

    def adapter(request):
        started.set()
        assert release.wait(2)
        return _result(request, "stale first result")

    window = make_window(adapter)
    widget = window._range_walk.widget
    window._range_walk.select_source(first)
    widget.down_edit.setText("1024")
    widget.neutral_edit.setText("0")
    widget.detect_button.click()
    assert started.wait(1)

    assert window._range_walk.select_source(second)
    assert "Selected:" in widget.report.toPlainText()
    assert second.name in widget.report.toPlainText()
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.source_path == second
    assert "stale first result" not in widget.report.toPlainText()
    assert "Stale Range-Walk marker preview was withheld" in (
        window.statusBar().currentMessage()
    )


def test_invalid_preview_recovers_without_changing_csv_source(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path)
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    widget.neutral_edit.setText("0")

    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "Full elevator-down Ele is required" in widget.report.toPlainText()
    assert widget.source_path == session.path.resolve()

    widget.down_edit.setText("1024")
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "Marker candidates: 5" in widget.report.toPlainText()


def test_worker_exclusion_safe_close_and_no_other_routing_or_persistence(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path)
    started = threading.Event()
    release = threading.Event()
    stall_calls = []

    def adapter(request):
        started.set()
        assert release.wait(2)
        return _result(request)

    window = make_window(
        adapter,
        stall_adapter=lambda path: stall_calls.append(path) or "stall report",
    )
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    widget.down_edit.setText("1024")
    widget.neutral_edit.setText("0")
    widget.detect_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    page = window.analysis_tabs.currentWidget()
    assert not [
        button for button in page.findChildren(QPushButton)
        if button.text() == "Analyse"
    ]
    assert not widget.choose_button.isEnabled()
    assert not window.choose_log_button.isEnabled()
    window.start_stall_analysis()
    assert stall_calls == []
    assert not (tmp_path / "packs.json").exists()
    assert not (tmp_path / "history.json").exists()

    window.close()
    assert window.isVisible()
    release.set()
    _wait_until(
        qt_app,
        lambda: window._analysis_thread is None and not window.isVisible(),
    )


def test_shared_bin_changes_do_not_change_range_walk_preview(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path)
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    widget.down_edit.setText("1024")
    widget.neutral_edit.setText("0")
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    report = widget.report.toPlainText()

    aircraft = tmp_path / "aircraft.bin"
    aircraft.touch()
    window.set_selected_log(aircraft)

    assert window.selected_log == aircraft.resolve()
    assert widget.source_path == session.path.resolve()
    assert widget.report.toPlainText() == report
