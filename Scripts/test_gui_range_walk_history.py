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


def _save_baseline(qt_app, window, source: Path):
    widget = _prepare_baseline(qt_app, window, source)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.persisted_record is not None
    return widget.persisted_record


def _prepare_additional(qt_app, window, source: Path, parent_id: str):
    widget = window._range_walk.widget
    assert window._range_walk.select_source(source)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.detect_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.next_button.click()
    widget.walk_type_combo.setCurrentIndex(
        widget.walk_type_combo.findData("additional")
    )
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    widget.parent_baseline_combo.setCurrentIndex(
        widget.parent_baseline_combo.findData(parent_id)
    )
    widget.walk1_label_edit.setText("Walk 2 — relocated receiver")
    widget.antenna_edit.setText("Receiver relocated lower in fuselage")
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


def test_unchanged_saved_baseline_cannot_start_duplicate_save(
    qt_app, tmp_path, make_window
):
    window = make_window()
    widget = _prepare_baseline(qt_app, window, _session(tmp_path).path)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    existing = widget.saved_baseline
    existing_summary = widget.baseline_summary.toPlainText()

    assert not widget.save_baseline_button.isEnabled()
    widget.save_baseline_button.click()

    assert widget.saved_baseline is existing
    assert "baseline saved" in widget.baseline_state_label.text()
    assert widget.baseline_summary.toPlainText() == existing_summary


def test_metadata_update_reuses_saved_identity_and_refreshes_history(
    qt_app, tmp_path, make_window, history_service
):
    window = make_window()
    widget = _prepare_baseline(qt_app, window, _session(tmp_path).path)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    original = widget.persisted_record
    assert original is not None

    widget.walk1_label_edit.setText("Corrected comparison baseline")
    widget.antenna_edit.setText(
        "Receiver, diversity antennas, lower tray, fore-aft/crosswise"
    )
    widget.tx_power_edit.setText("250 mW")
    assert widget.persisted_record is original
    assert widget.save_baseline_button.text() == "Update saved Walk 1"
    assert widget.save_baseline_button.isEnabled()
    widget.save_baseline_button.click()
    assert not widget.walk1_label_edit.isEnabled()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    updated = widget.persisted_record
    assert updated is not None
    assert updated.baseline_id == original.baseline_id
    assert updated.created_at_utc == original.created_at_utc
    assert updated.csv_sha256 == original.csv_sha256
    assert updated.stored_csv_path == original.stored_csv_path
    assert updated.candidates == original.candidates
    assert updated.landmarks == original.landmarks
    assert updated.landmark_names == original.landmark_names
    assert updated.turnaround == original.turnaround
    assert updated.label == "Corrected comparison baseline"
    assert updated.settings.tx_power == "250 mW"
    assert "baseline updated" in widget.baseline_state_label.text()
    assert "Baseline radio configuration:" in widget.baseline_summary.toPlainText()
    assert len(
        RangeWalkHistoryStore(
            history_service.history_path,
            history_service.evidence_dir,
        ).records
    ) == 1

    widget.baseline_history_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    report = widget.history_report.toPlainText()
    assert "Corrected comparison baseline" in report
    assert "Baseline radio configuration:" in report
    assert "fore-aft/crosswise" in report


def test_source_mutation_after_detection_is_rejected_and_requires_redetection(
    qt_app, tmp_path, make_window, history_service
):
    source = _session(tmp_path).path
    window = make_window()
    widget = _prepare_baseline(qt_app, window, source)
    source.write_text(source.read_text() + "mutated after detection\n")

    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.persisted_record is None
    assert "detect markers again" in widget.baseline_state_label.text()
    assert not history_service.history_path.exists()


def test_newer_metadata_is_not_overwritten_by_completed_update(
    qt_app, tmp_path, make_window, history_service
):
    started = threading.Event()
    release = threading.Event()

    class DelayedUpdateService(RangeWalkHistoryService):
        def update(self, request):
            started.set()
            assert release.wait(2)
            return super().update(request)

    service = DelayedUpdateService(
        history_path=history_service.history_path,
        evidence_dir=history_service.evidence_dir,
    )
    window = make_window(service)
    widget = _prepare_baseline(qt_app, window, _session(tmp_path).path)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.walk1_label_edit.setText("Submitted correction")
    widget.save_baseline_button.click()
    assert started.wait(1)
    assert not widget.walk1_label_edit.isEnabled()
    widget.walk1_label_edit.setText("Newer visible correction")
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.walk1_label_edit.text() == "Newer visible correction"
    assert widget.persisted_record.label == "Submitted correction"
    assert widget.save_baseline_button.text() == "Update saved Walk 1"
    assert "visible draft changed" in widget.baseline_state_label.text()


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


def test_additional_walk_requires_explicit_mapping_and_persists_missing_landmark(
    qt_app, tmp_path, make_window, history_service
):
    window = make_window()
    parent = _save_baseline(
        qt_app, window, _session(tmp_path, name="baseline.csv").path
    )
    source = _session(
        tmp_path,
        name="walk2.csv",
        holds=(2, 8, 14, 20),
    ).path
    widget = _prepare_additional(qt_app, window, source, parent.baseline_id)

    assert [combo.currentData() for combo in widget.candidate_combos] == [
        None,
        None,
        None,
        None,
        None,
    ]
    assert all(field.isReadOnly() for field in widget.landmark_name_edits)
    assert "Baseline ID:" in widget.parent_reference.toPlainText()
    assert "Field landmark 5" in widget.parent_reference.toPlainText()
    for combo, number in zip(widget.candidate_combos, (1, 2, None, 3, 4)):
        combo.setCurrentIndex(combo.findData(number))

    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    store = RangeWalkHistoryStore(
        history_service.history_path, history_service.evidence_dir
    )
    assert len(store.records) == 1
    assert len(store.walks) == 1
    saved = store.walks[0]
    assert saved.parent_baseline_id == parent.baseline_id
    assert saved.candidate_numbers == (1, 2, None, 3, 4)
    assert saved.settings == parent.settings
    assert saved.confirmed_landmark_count == 4
    assert saved.complete_section_count == 2
    summary = widget.baseline_summary.toPlainText()
    assert "Field landmark 3: Missing marker evidence" in summary
    assert "Available complete sections: 2/4" in summary
    assert not widget.save_baseline_button.isEnabled()


def test_parent_selection_clears_mapping_but_same_parent_refresh_preserves_it(
    qt_app, tmp_path, make_window
):
    window = make_window()
    widget = _prepare_baseline(
        qt_app, window, _session(tmp_path, name="parent1.csv").path
    )
    widget.tx_power_edit.setText("100 mW")
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    first = widget.persisted_record
    assert first is not None

    widget = _prepare_baseline(
        qt_app, window, _session(tmp_path, name="parent2.csv", down=-1024).path
    )
    widget.tx_power_edit.setText("250 mW")
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    second = widget.persisted_record
    assert second is not None

    widget = _prepare_additional(
        qt_app,
        window,
        _session(tmp_path, name="walk2.csv", holds=(2, 8, 14, 20)).path,
        first.baseline_id,
    )
    for combo, number in zip(widget.candidate_combos, (1, 2, None, 3, 4)):
        combo.setCurrentIndex(combo.findData(number))
    selected = [1, 2, None, 3, 4]
    assert [combo.currentData() for combo in widget.candidate_combos] == selected
    assert widget.tx_power_edit.text() == "100 mW"

    widget.baseline_history_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert [combo.currentData() for combo in widget.candidate_combos] == selected
    widget.history_back_button.click()

    widget.parent_baseline_combo.setCurrentIndex(
        widget.parent_baseline_combo.findData(second.baseline_id)
    )
    assert [combo.currentData() for combo in widget.candidate_combos] == [None] * 5
    assert second.baseline_id in widget.parent_reference.toPlainText()
    assert widget.tx_power_edit.text() == "250 mW"

    widget.parent_baseline_combo.setCurrentIndex(0)
    assert [combo.currentData() for combo in widget.candidate_combos] == [None] * 5
    assert all(not field.text() for field in widget.landmark_name_edits)
    assert all(
        not field.text()
        for field in (
            widget.tx_power_edit,
            widget.packet_rate_edit,
            widget.rf_mode_edit,
            widget.dynamic_power_edit,
        )
    )
    assert "Select a validated" in widget.parent_reference.toPlainText()


def test_workflow_switch_preserves_saved_baseline_update_state(
    qt_app, tmp_path, make_window
):
    window = make_window()
    widget = _prepare_baseline(qt_app, window, _session(tmp_path).path)
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    saved = widget.persisted_record
    assert saved is not None
    assert not widget.save_baseline_button.isEnabled()

    widget.walk_type_combo.setCurrentIndex(
        widget.walk_type_combo.findData("additional")
    )
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.save_baseline_button.text() == "Save additional walk"
    widget.walk_type_combo.setCurrentIndex(
        widget.walk_type_combo.findData("baseline")
    )
    assert widget.persisted_record == saved
    assert not widget.save_baseline_button.isEnabled()
    assert "baseline saved" in widget.baseline_state_label.text()

    widget.walk1_label_edit.setText("Corrected baseline label")
    assert widget.save_baseline_button.text() == "Update saved Walk 1"
    widget.walk_type_combo.setCurrentIndex(
        widget.walk_type_combo.findData("additional")
    )
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.save_baseline_button.text() == "Save additional walk"
    widget.walk_type_combo.setCurrentIndex(
        widget.walk_type_combo.findData("baseline")
    )
    assert widget.walk1_label_edit.text() == "Corrected baseline label"
    assert widget.save_baseline_button.text() == "Update saved Walk 1"
    assert widget.save_baseline_button.isEnabled()


def test_additional_save_failure_uses_range_walk_error_label(
    qt_app, tmp_path, make_window, history_service
):
    window = make_window()
    parent = _save_baseline(
        qt_app, window, _session(tmp_path, name="parent.csv").path
    )
    source = _session(tmp_path, name="walk2.csv", down=-1024).path
    widget = _prepare_additional(qt_app, window, source, parent.baseline_id)
    for combo, number in zip(widget.candidate_combos, (1, 2, 3, 4, 5)):
        combo.setCurrentIndex(combo.findData(number))
    source.write_text(source.read_text() + "modified after detection\n")
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "Range-Walk save failed" in widget.baseline_state_label.text()
    assert "detect markers again" in widget.baseline_state_label.text()
    assert not RangeWalkHistoryStore(
        history_service.history_path, history_service.evidence_dir
    ).walks


def test_restarted_history_groups_additional_walk_under_parent(
    qt_app, tmp_path, make_window
):
    window = make_window()
    parent = _save_baseline(
        qt_app, window, _session(tmp_path, name="baseline.csv").path
    )
    widget = _prepare_additional(
        qt_app,
        window,
        _session(tmp_path, name="walk2.csv", down=-1024).path,
        parent.baseline_id,
    )
    for combo, number in zip(widget.candidate_combos, (1, 2, 3, 4, 5)):
        combo.setCurrentIndex(combo.findData(number))
    widget.save_baseline_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    reopened = make_window()
    reopened_widget = reopened._range_walk.widget
    reopened_widget.page1_history_button.click()
    _wait_until(qt_app, lambda: reopened._analysis_thread is None)
    report = reopened_widget.history_report.toPlainText()

    assert parent.baseline_id in report
    assert "Walk 2 — relocated receiver" in report
    assert "Test radio configuration: Receiver relocated lower in fuselage" in report
    assert "Confirmed landmarks: 5/5" in report
    assert "Available complete sections: 4/4" in report
    assert "Evidence integrity: managed CSV checksum validated" in report
    assert "Comparisons are not yet available" in report


def test_stale_additional_walk_result_does_not_replace_newer_visible_draft(
    qt_app, tmp_path, make_window, history_service
):
    started = threading.Event()
    release = threading.Event()

    class DelayedWalkService(RangeWalkHistoryService):
        def save_additional_walk(self, request):
            started.set()
            assert release.wait(2)
            return super().save_additional_walk(request)

    service = DelayedWalkService(
        history_path=history_service.history_path,
        evidence_dir=history_service.evidence_dir,
    )
    window = make_window(service)
    parent = _save_baseline(
        qt_app, window, _session(tmp_path, name="baseline.csv").path
    )
    widget = _prepare_additional(
        qt_app,
        window,
        _session(tmp_path, name="walk2.csv", down=-1024).path,
        parent.baseline_id,
    )
    for combo, number in zip(widget.candidate_combos, (1, 2, 3, 4, 5)):
        combo.setCurrentIndex(combo.findData(number))

    widget.save_baseline_button.click()
    assert started.wait(1)
    widget.walk1_label_edit.setText("Newer unsaved walk label")
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.walk1_label_edit.text() == "Newer unsaved walk label"
    assert "visible draft changed" in widget.baseline_state_label.text()
    store = RangeWalkHistoryStore(
        history_service.history_path, history_service.evidence_dir
    )
    assert len(store.walks) == 1
    assert store.walks[0].label == "Walk 2 — relocated receiver"
