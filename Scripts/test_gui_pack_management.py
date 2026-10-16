"""Focused tests for GUI Battery Pack Management workflows."""

import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from core.battery_pack_store import (
    BatteryPackStore,
    BatteryPackStoreError,
    LogPackAssociation,
    LogPackState,
    fingerprint_log,
)
import core.battery_pack_store as pack_store_module
from gui import MainWindow
from gui.pack_management_adapter import (
    BatteryPackManagementService,
    PackManagementState,
    StalePackManagementStateError,
)


def _service(tmp_path, **kwargs):
    return BatteryPackManagementService(
        pack_store_path=tmp_path / "packs.json",
        history_store_path=tmp_path / "history.json",
        **kwargs,
    )


def _bin(tmp_path, name, content=b"BIN evidence"):
    path = tmp_path / name
    path.write_bytes(content)
    return path.resolve()


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def _answer_confirmation(button):
    """Click a real QMessageBox standard button from its modal event loop."""

    def answer():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        target = dialog.button(button)
        assert target is not None
        target.click()

    QTimer.singleShot(25, answer)


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(service, **adapters):
        window = MainWindow(pack_management_service=service, **adapters)
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a management worker active")
        window.close()
    qt_app.processEvents()


def test_management_starts_read_only_without_packs_or_selected_bin(
    tmp_path,
    make_window,
):
    service = _service(tmp_path)
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")

    assert window.pack_selected_bin_value.text() == "No BIN selected"
    assert window.pack_association_value.text() == "Unseen"
    assert window.pack_assign_combo.count() == 0
    assert not window.pack_assign_button.isEnabled()
    assert not window.pack_create_button.isEnabled()
    assert not window.pack_rename_button.isEnabled()
    assert not window.pack_record_history_button.isEnabled()
    assert not (tmp_path / "packs.json").exists()
    assert not (tmp_path / "history.json").exists()


def test_management_has_no_analyse_button_and_cannot_dispatch_stall(
    tmp_path,
    qt_app,
    make_window,
):
    stall_calls = []
    window = make_window(
        _service(tmp_path),
        stall_adapter=lambda path: stall_calls.append(path) or "Stall report",
    )
    window.show_analysis_tab("Battery Pack Management")
    qt_app.processEvents()
    page = window.analysis_tabs.currentWidget()

    assert window.overview_buttons[
        "Battery Pack Management"
    ].description() == "Manage pack identities and log associations."
    assert [
        button
        for button in page.findChildren(QPushButton)
        if button.text() == "Analyse"
    ] == []
    assert stall_calls == []


def test_lookup_preserves_unseen_tracked_not_tracked_and_content_identity(tmp_path):
    service = _service(tmp_path)
    original = _bin(tmp_path, "original.bin", b"identical")
    renamed_copy = _bin(tmp_path, "renamed.BIN", b"identical")
    omitted = _bin(tmp_path, "omitted.bin", b"other")

    unseen = service.lookup(original)
    assert unseen.association == LogPackAssociation(LogPackState.UNSEEN)
    assert unseen.pack_ids == ()

    tracked = service.create_and_assign(unseen, "Pack A").state
    same_content = service.lookup(renamed_copy)
    assert same_content.fingerprint == tracked.fingerprint
    assert same_content.association == LogPackAssociation(
        LogPackState.TRACKED,
        "Pack A",
    )

    store = BatteryPackStore(tmp_path / "packs.json")
    store.mark_not_tracked(fingerprint_log(omitted))
    assert service.lookup(omitted).association == LogPackAssociation(
        LogPackState.NOT_TRACKED
    )


def test_assign_create_and_global_rename_reload_all_associations(tmp_path):
    service = _service(tmp_path)
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")

    first_state = service.lookup(first)
    created = service.create_and_assign(first_state, "Pack A")
    second_state = service.lookup(second)
    service.create_and_assign(second_state, "Pack B")
    assigned = service.assign_existing(service.lookup(second), "Pack A")
    renamed = service.rename(assigned.state, "Pack A", "Pack C")

    assert created.changed
    assert assigned.state.association.pack_id == "Pack A"
    assert renamed.state.pack_ids == ("Pack C", "Pack B")
    assert service.lookup(first).association.pack_id == "Pack C"
    assert service.lookup(second).association.pack_id == "Pack C"


def test_duplicate_invalid_and_unchanged_operations_do_not_rewrite_store(tmp_path):
    service = _service(tmp_path)
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")
    tracked = service.create_and_assign(service.lookup(first), "Pack A").state
    original = (tmp_path / "packs.json").read_bytes()

    unchanged_assignment = service.assign_existing(tracked, "Pack A")
    unchanged_name = service.rename(tracked, "Pack A", " Pack A ")
    assert not unchanged_assignment.changed
    assert not unchanged_name.changed
    assert (tmp_path / "packs.json").read_bytes() == original

    second_state = service.lookup(second)
    with pytest.raises(BatteryPackStoreError, match="already exists"):
        service.create_and_assign(second_state, "Pack A")
    with pytest.raises(BatteryPackStoreError, match="non-empty"):
        service.create_and_assign(second_state, "   ")
    assert (tmp_path / "packs.json").read_bytes() == original


def test_confirmation_cancellation_leaves_persistent_bytes_unchanged(
    tmp_path,
    qt_app,
    make_window,
    monkeypatch,
):
    service = _service(tmp_path)
    seed = _bin(tmp_path, "seed.bin", b"seed")
    selected = _bin(tmp_path, "selected.bin", b"selected")
    service.create_and_assign(service.lookup(seed), "Pack A")
    original = (tmp_path / "packs.json").read_bytes()
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    confirmations = []

    def cancel(title, message):
        confirmations.append((title, message))
        return False

    monkeypatch.setattr(window, "_confirm_pack_action", cancel)

    window.pack_assign_button.click()
    window.pack_create_edit.setText("Pack B")
    window.pack_create_button.click()
    window.pack_rename_edit.setText("Pack C")
    window.pack_rename_button.click()

    assert window._analysis_thread is None
    assert (tmp_path / "packs.json").read_bytes() == original

    window.set_selected_log(seed)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.pack_record_history_button.isEnabled()
    window.pack_record_history_button.click()

    assert window._analysis_thread is None
    assert not (tmp_path / "history.json").exists()
    confirmation_text = "\n".join(message for _title, message in confirmations)
    assert "Source BIN: selected.bin" in confirmation_text
    assert "Current association: Unseen" in confirmation_text
    assert "Proposed Pack ID: Pack A" in confirmation_text
    assert "New Pack ID: Pack B" in confirmation_text
    assert "every associated BIN identity" in confirmation_text
    assert "Source BIN: seed.bin" in confirmation_text
    assert "Tracked Pack ID: Pack A" in confirmation_text


def test_write_failure_preserves_prior_store_bytes(tmp_path, monkeypatch):
    service = _service(tmp_path)
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")
    service.create_and_assign(service.lookup(first), "Pack A")
    second_state = service.lookup(second)
    original = (tmp_path / "packs.json").read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(pack_store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="atomic replace"):
        service.assign_existing(second_state, "Pack A")

    assert (tmp_path / "packs.json").read_bytes() == original


def test_history_recording_is_explicit_and_repeat_run_reports_zero(tmp_path):
    calls = []
    additions = iter((2, 0))
    flight_log = object()
    history_store = object()

    class Reader:
        def __init__(self, path, config=None):
            calls.append(("reader", path, config))

        def read(self):
            calls.append(("read",))
            return flight_log

    class Recorder:
        def __init__(self, config):
            self.config = config

        def record(self, *args):
            calls.append(("record", self.config, *args))
            return next(additions)

    config = object()
    service = _service(
        tmp_path,
        config_factory=lambda path: config if path == "Config/battery.yaml" else None,
        reader_factory=Reader,
        recorder_factory=Recorder,
        history_store_factory=lambda path: history_store,
    )
    selected = _bin(tmp_path, "flight.bin")
    tracked = service.create_and_assign(service.lookup(selected), "Pack A").state

    assert not any(call[0] == "record" for call in calls)
    renamed = service.rename(tracked, "Pack A", "Pack B")
    assert not any(call[0] == "record" for call in calls)

    first = service.record_history(renamed.state)
    second = service.record_history(first.state)

    assert first.observations_added == 2
    assert first.changed
    assert "2 new AUTO takeoff observations" in first.message
    assert second.observations_added == 0
    assert not second.changed
    assert "0 new AUTO takeoff observations" in second.message
    records = [call for call in calls if call[0] == "record"]
    assert len(records) == 2
    assert records[0][2:] == (
        flight_log,
        selected,
        fingerprint_log(selected),
        "Pack B",
        history_store,
    )


def test_stale_association_is_rejected_before_mutation(tmp_path):
    service = _service(tmp_path)
    selected = _bin(tmp_path, "selected.bin")
    state = service.create_and_assign(service.lookup(selected), "Pack A").state
    store = BatteryPackStore(tmp_path / "packs.json")
    store.create_and_associate("f" * 64, "Pack B")
    store.associate(state.fingerprint, "Pack B")
    before = (tmp_path / "packs.json").read_bytes()

    with pytest.raises(StalePackManagementStateError, match="association changed"):
        service.rename(state, "Pack A", "Pack C")

    assert (tmp_path / "packs.json").read_bytes() == before


def test_confirmed_assignment_refreshes_controls_without_history_write(
    tmp_path,
    qt_app,
    make_window,
    monkeypatch,
):
    recorder_calls = []
    service = _service(
        tmp_path,
        recorder_factory=lambda _config: recorder_calls.append("created"),
    )
    seed = _bin(tmp_path, "seed.bin", b"seed")
    selected = _bin(tmp_path, "selected.bin", b"selected")
    service.create_and_assign(service.lookup(seed), "Pack A")
    window = make_window(service)
    monkeypatch.setattr(window, "_confirm_pack_action", lambda *_args: True)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert window.pack_association_value.text() == "Unseen"
    window.pack_assign_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert window.pack_association_value.text() == "Tracked — Pack A"
    assert window.pack_record_history_button.isEnabled()
    assert recorder_calls == []
    assert "Assigned selected.bin to Pack ID Pack A" in window.report_for(
        "Battery Pack Management"
    ).toPlainText()


def test_real_yes_confirmation_persists_rename_and_refreshes_both_dropdowns(
    tmp_path,
    qt_app,
    make_window,
):
    store_path = tmp_path / "packs.json"
    selected = _bin(tmp_path, "selected.bin", b"selected")
    matching = _bin(tmp_path, "matching.bin", b"matching")
    lipo_3900 = _bin(tmp_path, "lipo-3900.bin", b"3900")
    lipo_2600 = _bin(tmp_path, "lipo-2600.bin", b"2600")
    store = BatteryPackStore(store_path)
    store.create_and_associate(fingerprint_log(lipo_3900), "LIPO-3900-01")
    store.create_and_associate(fingerprint_log(selected), "50S-P1")
    store.create_and_associate(fingerprint_log(lipo_2600), "LIPO-2600-01")
    store.associate(fingerprint_log(matching), "50S-P1")
    window = make_window(_service(tmp_path))
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_rename_combo.setCurrentText("50S-P1")
    window.pack_rename_edit.setText("50S-PC1")

    _answer_confirmation(QMessageBox.StandardButton.Yes)
    window.pack_rename_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    reloaded = BatteryPackStore(store_path)
    assert reloaded.pack_ids == (
        "LIPO-3900-01",
        "50S-PC1",
        "LIPO-2600-01",
    )
    assert "50S-P1" not in reloaded.pack_ids
    assert reloaded.association_for(fingerprint_log(selected)).pack_id == "50S-PC1"
    assert reloaded.association_for(fingerprint_log(matching)).pack_id == "50S-PC1"
    for combo in (window.pack_assign_combo, window.pack_rename_combo):
        assert [combo.itemText(index) for index in range(combo.count())] == [
            "LIPO-3900-01",
            "50S-PC1",
            "LIPO-2600-01",
        ]
        assert combo.currentText() == "50S-PC1"
    assert "Renamed Pack ID 50S-P1 to 50S-PC1 for all associated BINs" in (
        window.report_for("Battery Pack Management").toPlainText()
    )


def test_real_cancel_confirmation_performs_no_rename_write(
    tmp_path,
    qt_app,
    make_window,
):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(selected), "50S-P1")
    store_path = tmp_path / "packs.json"
    before = store_path.read_bytes()
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_rename_combo.setCurrentText("50S-P1")
    window.pack_rename_edit.setText("50S-PC1")

    _answer_confirmation(QMessageBox.StandardButton.Cancel)
    window.pack_rename_button.click()
    qt_app.processEvents()

    assert window._analysis_thread is None
    assert store_path.read_bytes() == before
    assert BatteryPackStore(store_path).pack_ids == ("50S-P1",)


def test_confirmed_rename_write_failure_reports_error_and_preserves_store(
    tmp_path,
    qt_app,
    make_window,
    monkeypatch,
):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(selected), "50S-P1")
    store_path = tmp_path / "packs.json"
    before = store_path.read_bytes()
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_rename_combo.setCurrentText("50S-P1")
    window.pack_rename_edit.setText("50S-PC1")

    def fail_replace(_source, _destination):
        raise OSError("simulated rename persistence failure")

    monkeypatch.setattr(pack_store_module.os, "replace", fail_replace)
    _answer_confirmation(QMessageBox.StandardButton.Yes)
    window.pack_rename_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    report = window.report_for("Battery Pack Management").toPlainText()
    assert "Battery Pack Management Error" in report
    assert "simulated rename persistence failure" in report
    assert store_path.read_bytes() == before


def test_stale_lookup_cannot_replace_newer_selection_and_blocks_other_work(
    tmp_path,
    qt_app,
    make_window,
):
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")
    started = threading.Event()
    release = threading.Event()
    calls = []
    battery_calls = []

    class Service:
        def lookup(self, path):
            calls.append(path)
            if path == first:
                started.set()
                assert release.wait(2)
            return PackManagementState(
                path,
                "a" * 64 if path == first else "b" * 64,
                LogPackAssociation(LogPackState.UNSEEN),
                (),
            )

    window = make_window(
        Service(),
        battery_adapter=lambda path: battery_calls.append(path) or "report",
    )
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(first)
    assert started.wait(1)
    qt_app.processEvents()

    assert not window.choose_log_button.isEnabled()
    window.start_battery_analysis()
    assert battery_calls == []
    window.set_selected_log(second)
    release.set()
    _wait_until(
        qt_app,
        lambda: window._analysis_thread is None
        and window._pack_management_state is not None
        and window._pack_management_state.log_path == second,
    )

    assert calls == [first, second]
    assert window.pack_selected_bin_value.text() == "second.bin"
    assert window._pack_management_state.fingerprint == "b" * 64


def test_failed_lookup_recovers_and_close_waits_for_management_worker(
    tmp_path,
    qt_app,
    make_window,
):
    selected = _bin(tmp_path, "selected.bin")
    release = threading.Event()
    attempts = 0

    class Service:
        def lookup(self, path):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("cannot hash BIN")
            assert release.wait(2)
            return PackManagementState(
                path,
                "c" * 64,
                LogPackAssociation(LogPackState.UNSEEN),
                (),
            )

    window = make_window(Service())
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "cannot hash BIN" in window.report_for(
        "Battery Pack Management"
    ).toPlainText()

    window._request_pack_lookup()
    _wait_until(qt_app, lambda: window._analysis_thread is not None)
    assert window.close() is False
    assert window._close_after_worker
    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    _wait_until(qt_app, lambda: not window.isVisible())
    assert attempts == 2
