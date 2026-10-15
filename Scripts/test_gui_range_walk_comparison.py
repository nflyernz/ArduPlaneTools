"""GUI tests for persisted Range-Walk RF comparison and graph presentation."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from core.range_walk import WalkSettings
from gui import MainWindow
from gui.pack_management_adapter import BatteryPackManagementService
from gui.pack_performance_adapter import BatteryPackPerformanceService
from analyses.range_walk_persisted import RangeWalkComparisonService
from gui.range_walk_history_adapter import RangeWalkHistoryService
from test_range_walk_comparison import _save_baseline, _save_walk, _services


def _wait_until(qt_app, predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


@pytest.fixture
def comparison_data(tmp_path):
    store, comparison = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    complete = _save_walk(tmp_path, store, parent)
    incomplete = _save_walk(
        tmp_path,
        store,
        parent,
        name="walk3.csv",
        rssi=-101,
        numbers=(1, 2, None, 4, 5),
    )
    history = RangeWalkHistoryService(
        history_path=store.path,
        evidence_dir=store.evidence_dir,
    )
    return store, history, comparison, parent, complete, incomplete


@pytest.fixture
def make_window(qt_app, tmp_path, comparison_data):
    windows = []
    _store, history, comparison, *_records = comparison_data

    def create(comparison_service=comparison):
        window = MainWindow(
            range_walk_history_service=history,
            range_walk_comparison_service=comparison_service,
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
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a Range-Walk comparison worker active")
        window.close()
    qt_app.processEvents()


def _open_history(qt_app, window):
    widget = window._range_walk.widget
    widget.page1_history_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    return widget


def _select_baseline_and_walks(widget, parent_id, *walk_ids):
    widget.comparison_baseline_combo.setCurrentIndex(
        widget.comparison_baseline_combo.findData(parent_id)
    )
    for index in range(widget.comparison_walk_list.count()):
        item = widget.comparison_walk_list.item(index)
        item.setSelected(item.data(256) in walk_ids)


def test_page3_selection_parent_change_and_refresh_lifecycle(
    qt_app, make_window, comparison_data
):
    _store, _history, _comparison, parent, complete, incomplete = comparison_data
    widget = _open_history(qt_app, make_window())
    _select_baseline_and_walks(widget, parent.baseline_id, complete.walk_id, incomplete.walk_id)

    assert widget.compare_button.isEnabled()
    assert len(widget.comparison_walk_list.selectedItems()) == 2
    widget.refresh_history_button.click()
    _wait_until(qt_app, lambda: widget.window()._analysis_thread is None)
    assert widget.comparison_baseline_combo.currentData() == parent.baseline_id
    assert {item.data(256) for item in widget.comparison_walk_list.selectedItems()} == {
        complete.walk_id,
        incomplete.walk_id,
    }

    widget.comparison_baseline_combo.setCurrentIndex(0)
    assert widget.comparison_walk_list.count() == 0
    assert not widget.compare_button.isEnabled()


def test_default_window_size_keeps_comparison_controls_readable(
    qt_app, make_window, comparison_data
):
    _store, _history, _comparison, parent, complete, _incomplete = comparison_data
    window = make_window()
    window.resize(1200, 780)
    widget = _open_history(qt_app, window)
    _select_baseline_and_walks(widget, parent.baseline_id, complete.walk_id)
    qt_app.processEvents()

    # Scroll the dashboard instead of squeezing its child widgets into 780px.
    assert widget.comparison_scroll.verticalScrollBar().maximum() > 0
    assert widget.comparison_walk_list.height() >= 112
    assert widget.comparison_table.height() == 282
    assert widget.graph_scroll.height() == 515
    assert widget.graph_label.minimumHeight() == 480

    assert widget.comparison_baseline_combo.currentText().startswith("Baseline — ")
    assert parent.antenna in widget.comparison_baseline_combo.currentText()
    tooltip = widget.comparison_baseline_combo.itemData(
        widget.comparison_baseline_combo.currentIndex(), 3
    )
    assert parent.label in tooltip
    assert parent.baseline_id in tooltip
    child = widget.comparison_walk_list.item(0)
    assert child.text().startswith("Comparison — ")
    assert complete.antenna in child.text()
    assert complete.label in child.toolTip()
    assert complete.walk_id in child.toolTip()

    widget.compare_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.comparison_table.item(0, 1).text() == (
        f"Baseline — {parent.antenna}"
    )
    assert widget.comparison_table.item(1, 1).text() == (
        f"Comparison — {complete.antenna}"
    )
    assert widget.graph_combo.itemText(1).startswith("Baseline — ")
    assert widget.graph_combo.itemText(2).startswith("Comparison — ")
    assert f"Saved label: {parent.label}" in widget.comparison_metadata.toPlainText()
    assert f"Saved label: {complete.label}" in widget.comparison_metadata.toPlainText()


def test_comparison_table_metadata_warnings_and_graphs(
    qt_app, make_window, comparison_data
):
    _store, _history, _comparison, parent, complete, incomplete = comparison_data
    window = make_window()
    widget = _open_history(qt_app, window)
    _select_baseline_and_walks(widget, parent.baseline_id, complete.walk_id, incomplete.walk_id)

    widget.compare_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.comparison_table.rowCount() == 12
    cells = [
        widget.comparison_table.item(row, column).text()
        for row in range(widget.comparison_table.rowCount())
        for column in range(widget.comparison_table.columnCount())
    ]
    assert "Missing landmark boundary" in cells
    assert "Start → Gate" in cells
    assert "Evidence integrity: managed CSV checksums validated" in widget.comparison_metadata.toPlainText()
    assert "consistent TX and RX antenna orientation" in widget.findChild(
        type(widget.comparison_state), "rangeWalkComparisonInterpretation"
    ).text()
    assert widget.graph_combo.count() == 4
    assert not widget.graph_label.pixmap().isNull()
    assert widget.export_graph_button.isEnabled()


def test_unknown_settings_warn_but_keep_rf_table(qt_app, tmp_path):
    store, comparison = _services(tmp_path)
    parent = _save_baseline(tmp_path, store, settings=WalkSettings())
    child = _save_walk(tmp_path, store, parent)
    history = RangeWalkHistoryService(
        history_path=store.path, evidence_dir=store.evidence_dir
    )
    window = MainWindow(
        range_walk_history_service=history,
        range_walk_comparison_service=comparison,
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
    widget = _open_history(qt_app, window)
    _select_baseline_and_walks(widget, parent.baseline_id, child.walk_id)
    widget.compare_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "Like-for-like RF settings not established." in widget.comparison_state.text()
    assert widget.comparison_table.item(1, 3).text() == "-82.0 dBm"
    window.close()


def test_stale_comparison_is_withheld_after_selection_change(
    qt_app, make_window, comparison_data
):
    _store, _history, comparison, parent, complete, incomplete = comparison_data
    started = threading.Event()
    release = threading.Event()

    class DelayedComparisonService:
        def compare(self, request):
            started.set()
            assert release.wait(4)
            return comparison.compare(request)

    window = make_window(DelayedComparisonService())
    widget = _open_history(qt_app, window)
    _select_baseline_and_walks(widget, parent.baseline_id, complete.walk_id)
    widget.compare_button.click()
    assert started.wait(1)
    _select_baseline_and_walks(widget, parent.baseline_id, incomplete.walk_id)
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget._comparison_result is None
    assert "Stale Range-Walk comparison result was withheld" in window.statusBar().currentMessage()


def test_export_and_reopen_use_managed_csv_without_originals(
    qt_app, tmp_path, make_window, comparison_data, monkeypatch
):
    store, _history, _comparison, parent, complete, _incomplete = comparison_data
    window = make_window()
    widget = _open_history(qt_app, window)
    _select_baseline_and_walks(widget, parent.baseline_id, complete.walk_id)
    widget.compare_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    destination = tmp_path / "exported.png"
    monkeypatch.setattr(
        "gui.range_walk_controller.QFileDialog.getSaveFileName",
        lambda *_args: (str(destination), "PNG image (*.png)"),
    )
    widget.export_graph_button.click()
    assert destination.is_file() and destination.stat().st_size > 1000

    Path(parent.original_csv_path).unlink()
    Path(complete.original_csv_path).unlink()
    reopened = make_window()
    reopened_widget = _open_history(qt_app, reopened)
    _select_baseline_and_walks(reopened_widget, parent.baseline_id, complete.walk_id)
    reopened_widget.compare_button.click()
    _wait_until(qt_app, lambda: reopened._analysis_thread is None)
    assert reopened_widget.comparison_table.rowCount() == 8
    assert store.path.is_file()
