"""Portable adapter and GUI tests for Range-Walk CSV marker preview."""

import os
from datetime import timedelta
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
    RangeWalkInspectionRequest,
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    analyse_range_walk_preview,
    estimate_ele_calibration,
    inspect_range_walk_csv,
)
from core.edgetx import EdgeTxRow, EdgeTxSession
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


def _ele_session(tmp_path, values, name="calibration.csv"):
    rows = [
        EdgeTxRow(
            BASE + timedelta(seconds=index / 10),
            {},
            None,
            "",
            "unavailable",
            value,
        )
        for index, value in enumerate(values)
    ]
    return EdgeTxSession(tmp_path / name, ("Ele",), rows, [])


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
    ("down", "expected_range"),
    ((1024, (0, 1024)), (-1024, (-1024, 0))),
)
def test_csv_inspection_reports_ele_extrema_without_assigning_direction(
    tmp_path, down, expected_range
):
    session = _session(tmp_path, down=down)

    inspection = inspect_range_walk_csv(
        RangeWalkInspectionRequest(session.path, 7)
    )

    assert (inspection.ele_min, inspection.ele_max) == expected_range
    assert inspection.request_id == 7
    assert inspection.calibration.neutral == 0
    assert (inspection.calibration.high if down > 0 else inspection.calibration.low) == down


def test_estimator_suggests_piper_like_neutral_and_sustained_endpoints(tmp_path):
    session = _ele_session(
        tmp_path,
        [2] * 100 + [1024] * 20 + [2] * 40 + [-1024] * 20 + [2] * 100,
    )

    suggestions = estimate_ele_calibration(session)

    assert suggestions.neutral == pytest.approx(2)
    assert suggestions.high == pytest.approx(1024)
    assert suggestions.low == pytest.approx(-1024)
    assert "sustained Ele plateaus" in suggestions.explanation


def test_estimator_rejects_isolated_endpoint_outliers(tmp_path):
    session = _ele_session(tmp_path, [2] * 100 + [1024, -1024] + [2] * 100)

    suggestions = estimate_ele_calibration(session)

    assert suggestions.neutral == pytest.approx(2)
    assert suggestions.high is None
    assert suggestions.low is None
    assert "no separated endpoint was sustained" in suggestions.explanation


def test_estimator_requires_a_clearly_dominant_neutral(tmp_path):
    session = _ele_session(tmp_path, [0] * 20 + [500] * 20 + [-500] * 20)

    suggestions = estimate_ele_calibration(session)

    assert suggestions.neutral is None
    assert suggestions.high is None
    assert suggestions.low is None
    assert "No clearly dominant" in suggestions.explanation


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
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "Observed Ele range: 0 to 1024" in widget.report.toPlainText()
    assert not widget.detect_button.isEnabled()
    assert "calibration unavailable or invalid" in widget.state_label.text()
    widget.higher_direction.click()
    assert "Suggested neutral: 0" in widget.suggestion_label.text()
    assert "full-down for the higher direction: 1024" in widget.suggestion_label.text()
    assert not widget.detect_button.isEnabled()
    widget.confirm_calibration.click()
    assert widget.detect_button.isEnabled()
    assert "Ready to detect" in widget.state_label.text()
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
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.higher_direction.click()
    widget.confirm_calibration.click()
    widget.detect_button.click()
    assert started.wait(1)

    assert window._range_walk.select_source(second)
    assert "Selected:" in widget.report.toPlainText()
    assert second.name in widget.report.toPlainText()
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.source_path == second
    assert "stale first result" not in widget.report.toPlainText()
    assert "Observed Ele range" in widget.report.toPlainText()
    assert not widget.confirm_calibration.isChecked()
    assert not widget.higher_direction.isChecked()


def test_source_change_during_inspection_withholds_old_suggestions(
    qt_app, tmp_path, make_window
):
    first = _session(tmp_path, name="first.csv", down=1024).path.resolve()
    second = _session(tmp_path, name="second.csv", down=-1024).path.resolve()
    started = threading.Event()
    release = threading.Event()

    def inspection_adapter(request):
        if request.source_path == first:
            started.set()
            assert release.wait(2)
        return inspect_range_walk_csv(request)

    window = make_window(range_walk_inspection_adapter=inspection_adapter)
    widget = window._range_walk.widget
    window._range_walk.select_source(first)
    assert started.wait(1)
    assert window._range_walk.select_source(second)
    assert not widget.confirm_calibration.isChecked()
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.source_path == second
    widget.lower_direction.click()
    assert "full-down for the lower direction: -1024" in (
        widget.suggestion_label.text()
    )
    assert "full-down for the higher direction: 1024" not in (
        widget.suggestion_label.text()
    )


def test_invalid_preview_recovers_without_changing_csv_source(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path)
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.manual_group.setChecked(True)
    widget.neutral_edit.setText("0")

    assert not widget.detect_button.isEnabled()
    assert "Full elevator-down Ele is required" in widget.state_label.text()
    assert widget.source_path == session.path.resolve()

    widget.down_edit.setText("invalid")
    assert not widget.detect_button.isEnabled()
    assert "must be numeric" in widget.state_label.text()
    widget.down_edit.setText("1024")
    assert widget.near_down_edit.text() == ""
    assert not widget.detect_button.isEnabled()
    widget.confirm_calibration.click()
    assert widget.detect_button.isEnabled()
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
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.higher_direction.click()
    widget.confirm_calibration.click()
    widget.detect_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    page = window.analysis_tabs.currentWidget()
    assert not [
        button for button in page.findChildren(QPushButton)
        if button.text() == "Analyse"
    ]
    assert not widget.choose_button.isEnabled()
    assert "Detection running" in widget.state_label.text()
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
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.higher_direction.click()
    widget.confirm_calibration.click()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    report = widget.report.toPlainText()

    aircraft = tmp_path / "aircraft.bin"
    aircraft.touch()
    window.set_selected_log(aircraft)

    assert window.selected_log == aircraft.resolve()
    assert widget.source_path == session.path.resolve()
    assert widget.report.toPlainText() == report


def test_calibration_guidance_and_failed_detection_keep_valid_csv(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path, down=-1024)

    def failure(_request):
        raise RuntimeError("preview failed")

    window = make_window(failure)
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    guidance = widget.calibration_guidance.text()
    assert "recorded in this EdgeTX CSV" in guidance
    assert "sustained neutral and endpoint values" in guidance
    assert "cannot determine which direction is elevator-down" in guidance
    assert "Observed Ele range: -1024 to 0" in widget.report.toPlainText()
    assert "Suggested neutral: 0" in widget.suggestion_label.text()
    assert "87.5%" in widget.near_down_edit.placeholderText()

    widget.lower_direction.click()
    assert "full-down for the lower direction: -1024" in (
        widget.suggestion_label.text()
    )
    assert not widget.detect_button.isEnabled()
    widget.confirm_calibration.click()
    assert widget.detect_button.isEnabled()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Detection failed" in widget.state_label.text()
    assert "preview failed" in widget.state_label.text()
    assert widget.source_path == session.path.resolve()
    assert widget.detect_button.isEnabled()


def test_direction_change_requires_new_confirmation(qt_app, tmp_path, make_window):
    session = _session(tmp_path, up=(30,))
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.higher_direction.click()
    widget.confirm_calibration.click()
    assert widget.detect_button.isEnabled()

    widget.lower_direction.click()
    assert not widget.confirm_calibration.isChecked()
    assert not widget.detect_button.isEnabled()
    assert "confirm it before" in widget.state_label.text()


def test_suggested_lower_direction_detects_negative_holds(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path, down=-1024)
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.lower_direction.click()
    widget.confirm_calibration.click()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Marker candidates: 5" in widget.report.toPlainText()


def test_manual_override_supports_negative_down_and_blank_threshold(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path, down=-1024)
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.manual_group.setChecked(True)
    widget.down_edit.setText("-1024")
    widget.neutral_edit.setText("0")
    assert widget.near_down_edit.text() == ""
    assert not widget.detect_button.isEnabled()
    widget.confirm_calibration.click()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Marker candidates: 5" in widget.report.toPlainText()


def test_unreliable_endpoint_requires_manual_fallback(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path, holds=(), short=(2,))
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.higher_direction.click()
    assert "Unavailable" in widget.suggestion_label.text()
    assert not widget.confirm_calibration.isEnabled()
    assert not widget.detect_button.isEnabled()
    assert "Advanced / Manual calibration" in widget.state_label.text()

    widget.manual_group.setChecked(True)
    widget.down_edit.setText("1024")
    widget.neutral_edit.setText("0")
    widget.confirm_calibration.click()
    assert widget.detect_button.isEnabled()
