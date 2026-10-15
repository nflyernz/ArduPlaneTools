"""GUI integration tests for persistent Range-Walk Walk 1 history."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from core.range_walk_history import RangeWalkHistoryStore
from gui import MainWindow
from gui.pack_management_adapter import BatteryPackManagementService
from gui.pack_performance_adapter import BatteryPackPerformanceService
from gui.range_walk_history_adapter import RangeWalkHistoryService
from test_range_walk import _session


def _wait_until(qt_app, predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


@pytest.fixture
def history_service(tmp_path):
    return RangeWalkHistoryService(
        history_path=tmp_path / "Data" / "range_walk_history.json",
        evidence_dir=tmp_path / "Data" / "range_walk_csv",
    )


@pytest.fixture
def make_window(qt_app, tmp_path, history_service):
    windows = []

    def create(service=history_service):
        window = MainWindow(
            range_walk_history_service=service,
            pack_management_service=BatteryPackManagementService(
                pack_store_path=tmp_path / "packs.json",
                history_store_path=tmp_path / "battery_history.json",
            ),
            pack_performance_service=BatteryPackPerformanceService(
                pack_store_path=tmp_path / "packs.json",
                history_store_path=tmp_path / "battery_history.json",
            ),
        )
        window.show()
        window.show_analysis_tab("Range-Walk Comparison")
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a Range-Walk history worker active")
        window.close()
    qt_app.processEvents()


def _prepare_baseline(qt_app, window, source: Path):
    widget = window._range_walk.widget
    assert window._range_walk.select_source(source)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.next_button.click()
    widget.antenna_edit.setText("Original receiver antenna below fuselage")
    for number, field in enumerate(widget.landmark_name_edits, start=1):
        field.setText(f"Field landmark {number}")
    return widget


def test_page2_persists_and_reopened_page3_loads_history(
    qt_app, tmp_path, make_window, history_service
):
    source = _session(tmp_path).path
    window = make_window()
    widget = _prepare_baseline(qt_app, window, source)

    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    saved = widget.saved_baseline
    assert saved is not None
    assert "Source CSV preserved" in widget.baseline_state_label.text()
    store = RangeWalkHistoryStore(
        history_service.history_path,
        history_service.evidence_dir,
    )
    record = store.validated_records()[0]
    assert record.landmarks == saved.landmarks
    assert record.turnaround == "Field landmark 5"

    source.unlink()
    reopened = make_window()
    reopened_widget = reopened._range_walk.widget
    assert reopened.selected_log is None
    reopened_widget.page1_history_button.click()
    _wait_until(qt_app, lambda: reopened._analysis_thread is None)

    report = reopened_widget.history_report.toPlainText()
    assert reopened_widget.pages.currentIndex() == 2
    assert "Walk 1 baseline 1" in report
    assert "Original receiver antenna below fuselage" in report
    assert "Field landmark 5 — turnaround" in report
    assert "Preserved source CSV: Yes" in report
    assert "Radio-local recording:" in report
    assert "incomplete RF settings" in report
    assert "Comparisons are not yet available" in report


def test_page3_navigation_preserves_page2_draft(qt_app, tmp_path, make_window):
    source = _session(tmp_path).path
    window = make_window()
    widget = _prepare_baseline(qt_app, window, source)
    widget.walk1_label_edit.setText("Operator draft label")

    widget.baseline_history_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.history_back_button.click()

    assert widget.pages.currentIndex() == 1
    assert widget.walk1_label_edit.text() == "Operator draft label"
    assert widget.candidate_combos[4].currentData() == 5


def test_duplicate_save_reports_error_without_losing_valid_baseline(
    qt_app, tmp_path, make_window
):
    window = make_window()
    widget = _prepare_baseline(qt_app, window, _session(tmp_path).path)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    existing = widget.saved_baseline
    existing_summary = widget.baseline_summary.toPlainText()

    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.saved_baseline is existing
    assert "save failed" in widget.baseline_state_label.text()
    assert "already saved" in widget.baseline_state_label.text()
    assert widget.baseline_summary.toPlainText() == existing_summary


def test_history_reports_corrupt_or_missing_managed_evidence(
    qt_app, tmp_path, make_window, history_service
):
    window = make_window()
    widget = _prepare_baseline(qt_app, window, _session(tmp_path).path)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    record = RangeWalkHistoryStore(
        history_service.history_path,
        history_service.evidence_dir,
    ).records[0]
    record.stored_csv_path.unlink()

    widget.baseline_history_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    report = widget.history_report.toPlainText()
    assert "Range-Walk History Error" in report
    assert "Managed CSV is missing" in report
    assert "Comparisons are not yet available" in report


def test_stale_save_result_is_withheld_after_source_change(
    qt_app, tmp_path, make_window, history_service
):
    started = threading.Event()
    release = threading.Event()
    calls = []

    class DelayedService(RangeWalkHistoryService):
        def save(self, request):
            calls.append(request)
            started.set()
            assert release.wait(2)
            return super().save(request)

    delayed = DelayedService(
        history_path=history_service.history_path,
        evidence_dir=history_service.evidence_dir,
    )
    first = _session(tmp_path, name="first.csv").path
    second = _session(tmp_path, name="second.csv").path
    window = make_window(delayed)
    widget = _prepare_baseline(qt_app, window, first)
    widget.save_baseline_button.click()
    assert started.wait(1)
    qt_app.processEvents()
    assert not widget.save_baseline_button.isEnabled()
    widget.save_baseline_button.click()
    assert len(calls) == 1

    assert window._range_walk.select_source(second)
    assert widget.saved_baseline is None
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.source_path == second.resolve()
    assert widget.saved_baseline is None
    assert len(
        RangeWalkHistoryStore(
            history_service.history_path,
            history_service.evidence_dir,
        ).records
    ) == 1
