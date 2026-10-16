"""Focused tests for read-only GUI Pack Performance reporting."""

import dataclasses
import os
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton

from analyses.battery import BatteryPackPerformancePresentation
from core import battery_pack_history
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_store import BatteryPackStore
from gui import MainWindow
from gui.pack_performance_adapter import (
    BatteryPackPerformanceService,
    PackPerformanceIndex,
)
from test_battery_pack_history import _observation
from test_battery_pack_performance import _event, _inputs


def _service(tmp_path):
    return BatteryPackPerformanceService(
        pack_store_path=tmp_path / "packs.json",
        history_store_path=tmp_path / "history.json",
    )


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(service, **kwargs):
        window = MainWindow(pack_performance_service=service, **kwargs)
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a Pack Performance worker active")
        window.close()
    qt_app.processEvents()


def _open_and_wait(qt_app, window):
    window.show_analysis_tab("Pack Performance")
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    return window._pack_performance.widget


def test_empty_refresh_needs_no_bin_and_creates_no_persistence(
    qt_app, tmp_path, make_window
):
    window = make_window(_service(tmp_path))
    widget = _open_and_wait(qt_app, window)

    assert window.selected_log is None
    assert widget.pack_selector.count() == 0
    assert not widget.view_button.isEnabled()
    assert widget.refresh_button.isEnabled()
    assert widget.report.toPlainText() == "No known Battery Pack IDs."
    assert "does not modify" in widget.read_only_notice.text()
    assert not (tmp_path / "packs.json").exists()
    assert not (tmp_path / "history.json").exists()


def test_shared_formatter_is_exactly_equivalent_to_cli_output(
    monkeypatch, capsys, tmp_path
):
    pack_store = BatteryPackStore(tmp_path / "packs.json")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    first_source = "1" * 64
    second_source = "2" * 64
    pack_store.create_and_associate(first_source, "Pack A")
    pack_store.associate(second_source, "Pack A")
    history.add_observations(
        [
            _event(first_source, "later.bin", 3_000_000),
            _event(first_source, "later.bin", 2_000_000),
            dataclasses.replace(
                _observation(
                    source_sha256=second_source,
                    source_filename="undated.bin",
                ),
                recorded_at_utc=None,
                gps_anchor_week=None,
                gps_anchor_week_ms=None,
                gps_anchor_time_us=None,
                gps_instance=None,
                gps_utc_offset_seconds=None,
                capacity_used_mah=None,
                average_current_a=None,
                peak_current_a=None,
                pre_load_voltage_v=None,
                minimum_loaded_voltage_v=None,
                voltage_sag_v=None,
                voltage_recovery_v=None,
            ),
        ]
    )
    pack_bytes = pack_store.path.read_bytes()
    history_bytes = history.path.read_bytes()
    report = _service(tmp_path).report("Pack A")

    _inputs(monkeypatch, "1")
    BatteryPackPerformancePresentation(pack_store, history).run()

    cli_output = capsys.readouterr().out
    report_start = cli_output.index("PACK PERFORMANCE REPORT")
    formatted_cli_report = cli_output[report_start:]
    assert formatted_cli_report == f"{report.text}\n"
    assert "FIRST TAKEOFF BY BATTERY SESSION" in report.text
    assert "ALL AUTO TAKEOFFS" in report.text
    assert "Unavailable" in report.text
    assert pack_store.path.read_bytes() == pack_bytes
    assert history.path.read_bytes() == history_bytes


def test_service_uses_current_ownership_and_newest_supported_history(
    monkeypatch, tmp_path
):
    versions = ("battery-load-v1", "battery-load-next")
    monkeypatch.setattr(
        battery_pack_history, "SUPPORTED_ANALYSIS_SEMANTICS", versions
    )
    pack_store = BatteryPackStore(tmp_path / "packs.json")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    selected = "1" * 64
    other = "2" * 64
    omitted = "3" * 64
    unseen = "4" * 64
    pack_store.create_and_associate(selected, "Pack A")
    pack_store.create_and_associate(other, "Pack B")
    pack_store.mark_not_tracked(omitted)
    old = _observation(
        source_sha256=selected,
        source_filename="selected.bin",
        semantics=versions[0],
    )
    new = dataclasses.replace(
        _observation(
            source_sha256=selected,
            source_filename="selected.bin",
            semantics=versions[1],
        ),
        capacity_used_mah=222.0,
    )
    history.add_observations(
        [
            old,
            new,
            _observation(source_sha256=other, source_filename="other.bin"),
            _observation(source_sha256=omitted, source_filename="omitted.bin"),
            _observation(source_sha256=unseen, source_filename="unseen.bin"),
        ]
    )

    initial = _service(tmp_path).report("Pack A").text
    pack_store.associate(other, "Pack A")
    pack_store.rename_pack("Pack A", "Pack Renamed")
    renamed = _service(tmp_path).report("Pack Renamed").text

    assert initial.count("Capacity used (mAh): 222.00") == 2
    assert "100.00" not in initial
    assert all(
        name not in initial
        for name in ("other.bin", "omitted.bin", "unseen.bin")
    )
    assert "Pack ID: Pack Renamed" in renamed
    assert "other.bin" in renamed
    assert "omitted.bin" not in renamed
    assert "unseen.bin" not in renamed


def test_report_action_handles_no_observations_and_preserves_store_bytes(
    qt_app, tmp_path, make_window
):
    store = BatteryPackStore(tmp_path / "packs.json")
    store.create_and_associate("1" * 64, "Pack A")
    before = store.path.read_bytes()
    window = make_window(_service(tmp_path))
    widget = _open_and_wait(qt_app, window)

    widget.view_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert "No stored AUTO takeoff observations" in widget.report.toPlainText()
    assert store.path.read_bytes() == before
    assert not (tmp_path / "history.json").exists()


def test_refresh_retains_existing_selection_and_explains_renamed_selection(
    qt_app, tmp_path, make_window
):
    store = BatteryPackStore(tmp_path / "packs.json")
    store.create_and_associate("1" * 64, "Pack A")
    store.create_and_associate("2" * 64, "Pack B")
    window = make_window(_service(tmp_path))
    widget = _open_and_wait(qt_app, window)
    widget.pack_selector.setCurrentText("Pack B")

    widget.refresh_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.selected_pack_id == "Pack B"

    BatteryPackStore(store.path).rename_pack("Pack B", "Pack C")
    widget.refresh_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert tuple(
        widget.pack_selector.itemText(index)
        for index in range(widget.pack_selector.count())
    ) == ("Pack A", "Pack C")
    assert widget.selected_pack_id == "Pack A"
    assert "Pack B is no longer registered" in widget.report.toPlainText()


def test_connected_tab_has_no_generic_analyse_or_stall_dispatch(
    qt_app, tmp_path, make_window
):
    stall_calls = []
    window = make_window(
        _service(tmp_path),
        stall_adapter=lambda path: stall_calls.append(path) or "Stall report",
    )
    widget = _open_and_wait(qt_app, window)
    page = window.analysis_tabs.currentWidget()

    assert window.overview_buttons[
        "Pack Performance"
    ].description() == "Compare battery-pack performance across logs."
    assert [
        button
        for button in page.findChildren(QPushButton)
        if button.text() == "Analyse"
    ] == []
    assert window.selected_log is None
    assert widget.refresh_button.isEnabled()
    assert stall_calls == []


def test_storage_error_recovers_on_refresh(qt_app, make_window):
    class RecoveringService:
        fail = True

        def refresh(self):
            if self.fail:
                raise OSError("history unavailable")
            return PackPerformanceIndex(("Pack A",))

        def report(self, _pack_id):
            raise AssertionError("report should not run")

    service = RecoveringService()
    window = make_window(service)
    widget = _open_and_wait(qt_app, window)
    assert "Unable to load Pack Performance data" in widget.report.toPlainText()

    service.fail = False
    widget.refresh_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert widget.selected_pack_id == "Pack A"
    assert widget.refresh_button.isEnabled()
    assert "Error" not in widget.report.toPlainText()


def test_close_waits_for_active_refresh_worker(qt_app, make_window):
    started = threading.Event()
    release = threading.Event()

    class BlockingService:
        def refresh(self):
            started.set()
            assert release.wait(2)
            return PackPerformanceIndex(("Pack A",))

    window = make_window(BlockingService())
    window.show_analysis_tab("Pack Performance")
    assert started.wait(1)
    qt_app.processEvents()

    window.close()
    assert window.isVisible()
    assert not window.choose_log_button.isEnabled()

    release.set()
    _wait_until(
        qt_app,
        lambda: window._analysis_thread is None and not window.isVisible(),
    )
