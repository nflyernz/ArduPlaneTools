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


def _request(path, *, inverse=False, request_id=1):
    return RangeWalkPreviewRequest(Path(path), inverse, request_id)


def _result(request, text="preview result"):
    return RangeWalkPreviewResult(
        request.source_path.resolve(),
        request.request_id,
        BASE,
        BASE,
        1,
        (),
        "higher",
        "higher",
        True,
        "Auto selected higher.",
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


@pytest.mark.parametrize(
    ("down", "expected_direction"),
    ((1024, "higher"), (-1024, "lower")),
)
def test_adapter_auto_detects_positive_and_negative_holds(
    tmp_path, down, expected_direction
):
    session = _session(tmp_path, down=down)

    result = analyse_range_walk_preview(_request(session.path))

    assert result.source_path == session.path.resolve()
    assert result.row_count == len(session.rows)
    assert result.recording_start == session.rows[0].clock
    assert result.recording_end == session.rows[-1].clock
    assert result.direction_used == expected_direction
    assert result.auto_preferred == expected_direction
    assert result.direction_reliable
    assert len(result.markers) == 5
    sign = "+" if expected_direction == "higher" else "-"
    assert f"Direction used: {expected_direction} ({sign}Ele)" in result.text
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


def test_auto_ignores_accidental_short_stick_movements(tmp_path):
    session = _session(tmp_path, short=(5, 11, 17, 23))

    result = analyse_range_walk_preview(_request(session.path))

    assert result.direction_used == "higher"
    assert len(result.markers) == 5
    assert [marker.onset for marker in result.markers] == [
        BASE + timedelta(seconds=value) for value in (2, 8, 14, 20, 26)
    ]


def test_inverse_uses_opposite_direction_and_does_not_promote_short_movement(tmp_path):
    session = _session(tmp_path, short=(5,))

    result = analyse_range_walk_preview(_request(session.path, inverse=True))

    assert result.direction_used == "lower"
    assert result.auto_preferred == "higher"
    assert len(result.markers) == 0
    assert "No complete elevator holds were detected in the inverse direction." in (
        result.text
    )
    assert "Try Inverse" not in result.text


def test_ambiguous_directions_are_reported_and_deterministic(tmp_path):
    session = _session(
        tmp_path,
        holds=(2, 8),
        up=(14, 20),
    )

    auto = analyse_range_walk_preview(_request(session.path))
    inverse = analyse_range_walk_preview(_request(session.path, inverse=True))

    assert auto.direction_used == "higher"
    assert auto.auto_preferred is None
    assert not auto.direction_reliable
    assert len(auto.markers) == 2
    assert "ambiguous or insufficient" in auto.assessment
    assert inverse.direction_used == "lower"
    assert len(inverse.markers) == 2


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


def test_adapter_rejects_missing_ele_consistently_with_inspection(tmp_path):
    session = _session(
        tmp_path,
        name="missing_ele.csv",
        header=[field for field in HEADER if field != "Ele"],
    )

    with pytest.raises(ValueError, match="one numeric Ele value on every CSV row"):
        analyse_range_walk_preview(_request(session.path))
    with pytest.raises(ValueError, match="one numeric Ele value on every CSV row"):
        inspect_range_walk_csv(RangeWalkInspectionRequest(session.path, 1))


def test_adapter_rejects_a_non_numeric_ele_row(tmp_path):
    session = _session(tmp_path)
    lines = session.path.read_text().splitlines()
    ele_index = lines[0].split(",").index("Ele")
    cells = lines[20].split(",")
    cells[ele_index] = "not-a-number"
    lines[20] = ",".join(cells)
    session.path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ValueError, match="one numeric Ele value on every CSV row"):
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
    assert widget.auto_button.isChecked()
    assert "Sustained neutral: 0" in widget.suggestion_label.text()
    assert "higher endpoint: 1024" in widget.suggestion_label.text()
    assert widget.findChild(type(widget.source_path_edit), "rangeWalkNeutralCalibration") is None
    assert widget.findChild(type(widget.source_path_edit), "rangeWalkNearDownCalibration") is None
    assert widget.detect_button.isEnabled()
    assert "Auto mode" in widget.state_label.text()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    report = widget.report.toPlainText()
    assert widget.source_path == session.path.resolve()
    assert dialog["args"][3] == "EdgeTX CSV files (*.csv *.CSV)"
    assert session.path.name in report
    assert str(session.path.resolve()) in report
    assert "CSV rows: 330" in report
    assert "Direction used: higher (+Ele)" in report
    assert "Marker candidates: 5" in report
    assert "onset 15:00:02.000" in report
    assert "higher (+Ele) direction; 5 marker candidate(s)" in widget.state_label.text()
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
    assert widget.auto_button.isChecked()


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
    assert widget.auto_button.isChecked()
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.source_path == second
    assert "lower endpoint: -1024" in widget.suggestion_label.text()
    assert "higher endpoint: 1024" not in widget.suggestion_label.text()


def test_no_clear_deflections_are_reported_without_changing_csv_source(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path, holds=(), short=(2,))
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.detect_button.isEnabled()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Marker candidates: 0" in widget.report.toPlainText()
    assert "No clear elevator stick deflections detected. Try Inverse." in (
        widget.report.toPlainText()
    )
    assert widget.source_path == session.path.resolve()


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
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    report = widget.report.toPlainText()

    aircraft = tmp_path / "aircraft.bin"
    aircraft.touch()
    window.set_selected_log(aircraft)

    assert window.selected_log == aircraft.resolve()
    assert widget.source_path == session.path.resolve()
    assert widget.report.toPlainText() == report


def test_auto_inverse_guidance_and_failed_detection_keep_valid_csv(
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
    assert "complete sustained holds and neutral returns" in guidance
    assert "Use Inverse to inspect the opposite direction" in guidance
    assert "Observed Ele range: -1024 to 0" in widget.report.toPlainText()
    assert "Sustained neutral: 0" in widget.suggestion_label.text()
    assert "lower endpoint: -1024" in widget.suggestion_label.text()
    assert widget.detect_button.isEnabled()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Detection failed" in widget.state_label.text()
    assert "preview failed" in widget.state_label.text()
    assert widget.source_path == session.path.resolve()
    assert widget.detect_button.isEnabled()


def test_auto_is_default_and_inverse_is_adjacent(qt_app, tmp_path, make_window):
    session = _session(tmp_path, up=(30,))
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.auto_button.isChecked()
    assert not widget.inverse_button.isChecked()
    assert widget.detect_button.isEnabled()

    widget.inverse_button.click()
    assert widget.inverse_button.isChecked()
    assert widget.detect_button.isEnabled()
    assert "Inverse mode" in widget.state_label.text()


def test_auto_detects_negative_holds_and_inverse_uses_positive_direction(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path, down=-1024, up=(30,))
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(session.path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Direction used: lower (-Ele)" in widget.report.toPlainText()
    assert "Marker candidates: 5" in widget.report.toPlainText()
    widget.inverse_button.click()
    assert window._analysis_thread is None
    assert "Direction used:" not in widget.report.toPlainText()
    assert "previous result is no longer shown" in widget.report.toPlainText()
    assert "previous result cleared" in widget.state_label.text()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Direction used: higher (+Ele)" in widget.report.toPlainText()
    assert "Marker candidates: 1" in widget.report.toPlainText()


def test_missing_neutral_evidence_reports_insufficient_data(
    qt_app, tmp_path, make_window
):
    session = _session(tmp_path)
    path = session.path
    lines = path.read_text().splitlines()
    ele_index = lines[0].split(",").index("Ele")
    rewritten = [lines[0]]
    for index, line in enumerate(lines[1:]):
        cells = line.split(",")
        cells[ele_index] = str(1024 if (index // 10) % 2 else -1024)
        rewritten.append(",".join(cells))
    path.write_text("\n".join(rewritten) + "\n")
    window = make_window()
    widget = window._range_walk.widget
    window._range_walk.select_source(path)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.detect_button.isEnabled()
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    report = widget.report.toPlainText()
    assert "Marker candidates: 0" in report
    assert "No clear elevator stick deflections detected. Try Inverse." in report
