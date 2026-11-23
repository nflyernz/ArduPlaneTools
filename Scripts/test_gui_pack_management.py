"""Focused tests for GUI Battery Pack Management workflows."""

import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import core.battery_pack_store as pack_store_module
from analyses.battery import pack_performance_observations
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_history_v2 import BatteryPackHistoryV2Store
from core.battery_pack_store import (
    BatteryPackStore,
    BatteryPackStoreError,
    LogPackAssociation,
    LogPackState,
    fingerprint_log,
)
from gui import MainWindow
from gui.pack_management_adapter import (
    BatteryPackManagementService,
    PackManagementState,
    StalePackManagementStateError,
)
from gui.pack_performance_adapter import BatteryPackPerformanceService
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
from test_battery_pack_history import _observation


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


def test_v2_record_control_is_separate_confirmed_and_uses_worker(
    tmp_path, qt_app, make_window, monkeypatch,
):
    from test_pilot_takeoff import _log as pilot_log

    class Reader:
        def __init__(self, _path, config=None):
            pass

        def read(self):
            return pilot_log()

    service = _service(tmp_path, reader_factory=Reader)
    source = _bin(tmp_path, "flight.bin")
    service.create_and_assign(service.lookup(source), "Pack A")
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(source)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.pack_record_history_button.isEnabled()
    assert window.pack_record_history_v2_button.isEnabled()
    confirmations = []
    monkeypatch.setattr(window, "_confirm_pack_action",
                        lambda title, message: confirmations.append((title, message)) or False)
    window.pack_record_history_v2_button.click()
    assert not (tmp_path / "battery_pack_history_v2.json").exists()
    assert "MANUAL and FBWA" in confirmations[0][1]
    assert "Assigned Pack ID: Pack A" in confirmations[0][1]
    monkeypatch.setattr(window, "_confirm_pack_action", lambda *_args: True)
    window.pack_record_history_v2_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None
                and "2 new v2 takeoff observations" in
                window.report_for("Battery Pack Management").toPlainText())
    assert "2 new v2 takeoff observations from flight.bin for Pack ID Pack A" in (
        window.report_for("Battery Pack Management").toPlainText()
    )
    v2_path = tmp_path / "battery_pack_history_v2.json"
    assert v2_path.exists()
    observations = BatteryPackHistoryV2Store(v2_path).observations
    assert len(observations) == 2
    assert {row.flight_mode for row in observations} == {"MANUAL", "FBWA"}
    assert all(row.takeoff_type == "PILOT_CONTROLLED"
               and row.pack_id_at_ingest == "Pack A" for row in observations)
    assert not (tmp_path / "history.json").exists()


def test_v2_record_worker_error_is_reported_without_history_write(
    tmp_path, qt_app, make_window, monkeypatch,
):
    service = _service(tmp_path)
    source = _bin(tmp_path, "flight.bin")
    service.create_and_assign(service.lookup(source), "Pack A")
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(source)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    monkeypatch.setattr(window, "_confirm_pack_action", lambda *_args: True)
    monkeypatch.setattr(service, "record_history_v2",
                        lambda _state: (_ for _ in ()).throw(ValueError("invalid v2 history")))
    window.pack_record_history_v2_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "invalid v2 history" in window.report_for("Battery Pack Management").toPlainText()
    assert not (tmp_path / "battery_pack_history_v2.json").exists()


def test_v2_button_tracks_selection_and_busy_state(tmp_path, qt_app, make_window):
    service = _service(tmp_path)
    tracked = _bin(tmp_path, "tracked.bin", b"tracked")
    unseen = _bin(tmp_path, "unseen.bin", b"unseen")
    service.create_and_assign(service.lookup(tracked), "Pack A")
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(unseen)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert not window.pack_record_history_v2_button.isEnabled()
    BatteryPackStore(tmp_path / "packs.json").mark_not_tracked(fingerprint_log(tracked))
    window.set_selected_log(tracked)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert not window.pack_record_history_v2_button.isEnabled()
    service.assign_existing(service.lookup(tracked), "Pack A")
    window.set_selected_log(unseen)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.set_selected_log(tracked)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.pack_record_history_v2_button.isEnabled()
    assert window.pack_record_history_button.isEnabled()
    window._analysis_thread = object()
    window._update_analysis_controls()
    assert not window.pack_record_history_v2_button.isEnabled()
    window._analysis_thread = None
    window._update_analysis_controls()


def test_v2_confirmation_selection_change_and_repeat_activation_do_not_start_twice(
    tmp_path, qt_app, make_window, monkeypatch,
):
    service = _service(tmp_path)
    selected = _bin(tmp_path, "selected.bin", b"selected")
    other = _bin(tmp_path, "other.bin", b"other")
    service.create_and_assign(service.lookup(selected), "Pack A")
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    calls = []
    monkeypatch.setattr(window, "_start_pack_mutation",
                        lambda *args: calls.append(args))

    def change_selection(*_args):
        window.set_selected_log(other)
        return True

    monkeypatch.setattr(window, "_confirm_pack_action", change_selection)
    window.record_pack_history_v2()
    assert calls == []
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    monkeypatch.setattr(window, "_confirm_pack_action", lambda *_args: True)

    def start_once(*args):
        calls.append(args)
        window._analysis_thread = object()

    monkeypatch.setattr(window, "_start_pack_mutation", start_once)
    window.record_pack_history_v2()
    window.record_pack_history_v2()
    assert len(calls) == 1 and calls[0][0] == "history_v2"
    window._analysis_thread = None
    assert window.pack_record_history_button.isEnabled()
    assert not (tmp_path / "battery_pack_history_v2.json").exists()


def test_service_archive_restore_and_delete_survive_restart(tmp_path):
    log = _bin(tmp_path, "flight.bin")
    service = _service(tmp_path)
    initial = service.lookup(log)
    assigned = service.create_and_assign(initial, "Pack 1").state
    archived = service.archive(assigned, "Pack 1").state
    assert archived.pack_ids == ()
    assert archived.archived_pack_ids == ("Pack 1",)
    assert _service(tmp_path).lookup(log).association.pack_id == "Pack 1"
    preview = service.preview_delete(archived, "Pack 1")
    assert len(preview.plan.log_fingerprints) == 1
    deleted = service.delete(archived, "Pack 1", preview).state
    assert deleted.pack_ids == deleted.archived_pack_ids == ()
    assert _service(tmp_path).lookup(log).association.state is LogPackState.NOT_TRACKED


def _deletion_cases(tmp_path):
    """Seed packs with associations, history, and both unused states."""
    store = BatteryPackStore(tmp_path / "packs.json")
    logs = {
        name: _bin(tmp_path, f"{name}.bin", name.encode())
        for name in ("associated", "historical", "unused", "archived")
    }
    for name, log in logs.items():
        store.create_and_associate(fingerprint_log(log), name)
    for name in ("historical", "unused", "archived"):
        store.mark_not_tracked(fingerprint_log(logs[name]))
    store.archive_pack("archived")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([
        _observation(
            source_sha256=fingerprint_log(logs["historical"]),
            pack_id="historical",
        )
    ])
    return _service(tmp_path), _bin(tmp_path, "selected.bin", b"selected")


def test_delete_preserves_unrelated_packs_and_history(tmp_path):
    service, selected = _deletion_cases(tmp_path)
    state = service.lookup(selected)
    assert state.pack_ids == ("associated", "historical", "unused")
    assert state.archived_pack_ids == ("archived",)
    assert state.unused_pack_ids == ("unused", "archived")

    pack_path = tmp_path / "packs.json"
    history_path = tmp_path / "history.json"
    before = pack_path.read_bytes(), history_path.read_bytes()
    preview = service.preview_delete(state, "associated")
    assert len(preview.plan.log_fingerprints) == 1
    assert preview.plan.observation_ids == ()
    service.delete(state, "associated", preview)
    service.delete(service.lookup(selected), "historical")
    service.delete(service.lookup(selected), "unused")
    service.delete(service.lookup(selected), "archived")
    reloaded = _service(tmp_path).lookup(selected)
    assert reloaded.unused_pack_ids == ()
    assert reloaded.pack_ids == ()
    assert reloaded.archived_pack_ids == ()
    assert BatteryPackHistoryStore(history_path).observations == ()
    assert pack_path.read_bytes() != before[0]


def test_delete_dropdown_offers_all_packs(tmp_path, qt_app, make_window):
    service, selected = _deletion_cases(tmp_path)
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    combo = window.pack_delete_combo
    assert [combo.itemText(index) for index in range(1, combo.count())] == [
        "associated", "historical", "unused", "archived"
    ]
    assert not window.pack_delete_button.isEnabled()
    combo.setCurrentText("archived")
    assert window.pack_delete_button.isEnabled()
    combo.setCurrentIndex(0)
    assert not window.pack_delete_button.isEnabled()


def test_pack_lifecycle_actions_work_without_selected_bin(
    tmp_path, qt_app, make_window, monkeypatch,
):
    seed = _bin(tmp_path, "seed.bin")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(seed), "Pack A")
    window = make_window(service)
    monkeypatch.setattr(window, "_confirm_pack_action", lambda *_args: True)
    monkeypatch.setattr(window, "_confirm_pack_deletion", lambda _preview: True)
    window.show_analysis_tab("Battery Pack Management")
    assert window.selected_log is None
    assert window.pack_rename_combo.findText("Pack A") >= 0
    assert not window.pack_assign_button.isEnabled()
    assert not window.pack_record_history_button.isEnabled()

    window.pack_archive_combo.setCurrentText("Pack A")
    window.pack_archive_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None
                and window.pack_restore_combo.findText("Pack A") >= 0)
    window.pack_restore_combo.setCurrentText("Pack A")
    window.pack_restore_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None
                and window.pack_archive_combo.findText("Pack A") >= 0)
    window.pack_rename_combo.setCurrentText("Pack A")
    window.pack_rename_edit.setText("Pack B")
    window.pack_rename_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None
                and window.pack_delete_combo.findText("Pack B") >= 0)
    window.pack_delete_combo.setCurrentText("Pack B")
    assert "seed.bin" in window.pack_delete_preview_text.toPlainText()
    window.pack_delete_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None
                and window.pack_delete_combo.findText("Pack B") == -1)
    assert BatteryPackStore(tmp_path / "packs.json").association_for(
        fingerprint_log(seed)
    ).state is LogPackState.NOT_TRACKED
    assert window.selected_log is None
    assert not window.pack_assign_button.isEnabled()
    assert not window.pack_record_history_button.isEnabled()


def test_delete_preview_lists_multiple_logs_and_confirmation_names(
    tmp_path, qt_app, make_window,
):
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(first), "Pack A")
    service.assign_existing(service.lookup(second), "Pack A")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([
        _observation(source_sha256=fingerprint_log(first), pack_id="Pack A"),
        _observation(source_sha256=fingerprint_log(second), pack_id="Pack A",
                     battery_instance=1),
    ])
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.pack_delete_combo.setCurrentText("Pack A")
    preview_text = window.pack_delete_preview_text.toPlainText()
    assert "Associated BIN logs: 2" in preview_text
    assert "first.bin" in preview_text
    assert "second.bin" in preview_text
    assert "Battery history observations to delete: 2" in preview_text
    seen = []

    def cancel():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        seen.append(dialog.text())
        next(button for button in dialog.buttons() if button.text() == "Cancel").click()

    QTimer.singleShot(25, cancel)
    window.pack_delete_button.click()
    assert "first.bin" in seen[0]
    assert "second.bin" in seen[0]
    assert "2 battery history observations" in seen[0]
    assert BatteryPackStore(tmp_path / "packs.json").pack_ids == ("Pack A",)


def test_legacy_delete_preview_labels_unknown_filename(tmp_path, make_window):
    fingerprint = "d" * 64
    path = tmp_path / "packs.json"
    path.write_text(json.dumps({
        "version": 3, "pack_ids": ["Legacy"], "archived_pack_ids": [],
        "retained_history_owners": {},
        "log_associations": {
            fingerprint: {"state": "tracked", "pack_id": "Legacy"},
        },
    }), encoding="utf-8")
    BatteryPackHistoryStore(tmp_path / "history.json").add_observations([
        _observation(source_sha256="e" * 64, source_filename="lookalike.bin",
                     pack_id="Different"),
    ])
    window = make_window(_service(tmp_path))
    window.show_analysis_tab("Battery Pack Management")
    window.pack_delete_combo.setCurrentText("Legacy")
    preview_text = window.pack_delete_preview_text.toPlainText()
    assert "Unknown filename — SHA-256 dddddddddddddddd…" in preview_text
    assert "Associated BIN logs: 1" in preview_text
    assert "Battery history observations to delete: 0" in preview_text
    assert "lookalike.bin" not in preview_text


def test_stale_pack_selection_blocks_delete_and_selection_clears_error(
    tmp_path, make_window, monkeypatch,
):
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(first), "Pack A")
    service.create_and_assign(service.lookup(second), "Pack B")
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.pack_delete_combo.setCurrentText("Pack A")
    store = BatteryPackStore(tmp_path / "packs.json")
    store.associate(fingerprint_log(second), "Pack A", second.name)
    before = store.path.read_bytes()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda _parent, _title, message: warnings.append(message))
    window.pack_delete_button.click()
    assert "refresh and try again" in warnings[0]
    assert store.path.read_bytes() == before
    window.pack_delete_combo.setCurrentText("Pack B")
    assert not window.report_for("Battery Pack Management").toPlainText().startswith(
        "Battery Pack Management Error"
    )
    assert "refresh and try again" in window.pack_delete_preview_text.toPlainText()


def test_delete_preview_and_cancel_leave_both_stores_unchanged(
    tmp_path, qt_app, make_window, monkeypatch,
):
    selected = _bin(tmp_path, "flight.bin")
    service = _service(tmp_path)
    assigned = service.create_and_assign(service.lookup(selected), "Mistake").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([
        _observation(source_sha256=assigned.fingerprint, pack_id="Mistake"),
        _observation(source_sha256=assigned.fingerprint, pack_id="Mistake", battery_instance=1),
    ])
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes(),
              selected.read_bytes())
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_delete_combo.setCurrentText("Mistake")
    observed = []

    def cancel(preview):
        observed.append(preview)
        return False

    monkeypatch.setattr(window, "_confirm_pack_deletion", cancel)
    window.pack_delete_button.click()
    assert len(observed[0].plan.log_fingerprints) == 1
    assert len(observed[0].plan.observation_ids) == 2
    assert window._analysis_thread is None
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes(),
            selected.read_bytes()) == before


def test_delete_rejects_stale_preview_and_keeps_persistence(tmp_path):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Mistake").state
    preview = service.preview_delete(state, "Mistake")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([_observation(source_sha256=state.fingerprint, pack_id="Mistake")])
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes())
    with pytest.raises(StalePackManagementStateError, match="changed after confirmation"):
        service.delete(state, "Mistake", preview)
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes()) == before


def test_delete_rolls_history_back_if_pack_write_fails(tmp_path, monkeypatch):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Mistake").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([_observation(source_sha256=state.fingerprint, pack_id="Mistake")])
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes())
    original_save = BatteryPackStore._save

    def fail_deletion(self, pack_ids, associations, archived_pack_ids=None,
                      history_owners=None, **kwargs):
        if "Mistake" not in pack_ids:
            raise OSError("simulated pack write failure")
        return original_save(self, pack_ids, associations, archived_pack_ids,
                             history_owners, **kwargs)

    monkeypatch.setattr(BatteryPackStore, "_save", fail_deletion)
    with pytest.raises(OSError, match="simulated pack write failure"):
        service.delete(state, "Mistake", service.preview_delete(state, "Mistake"))
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes()) == before


def test_delete_rolls_both_files_back_after_late_pack_failure(tmp_path, monkeypatch):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Mistake").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([_observation(source_sha256=state.fingerprint, pack_id="Mistake")])
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes())
    original_save = BatteryPackStore._save

    def fail_after_write(self, pack_ids, associations, archived_pack_ids=None,
                         history_owners=None, **kwargs):
        original_save(self, pack_ids, associations, archived_pack_ids,
                      history_owners, **kwargs)
        if "Mistake" not in pack_ids:
            raise OSError("simulated failure after pack replace")

    monkeypatch.setattr(BatteryPackStore, "_save", fail_after_write)
    with pytest.raises(OSError, match="after pack replace"):
        service.delete(state, "Mistake", service.preview_delete(state, "Mistake"))
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes()) == before


def test_reassigned_log_history_deletes_only_original_owner(tmp_path):
    selected = _bin(tmp_path, "selected.bin")
    other = _bin(tmp_path, "other.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Old").state
    service.create_and_assign(service.lookup(other), "New")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([_observation(source_sha256=state.fingerprint, pack_id="Old")])
    BatteryPackStore(tmp_path / "packs.json").associate(state.fingerprint, "New")
    state = service.lookup(selected)
    preview = service.preview_delete(state, "Old")
    assert len(preview.plan.observation_ids) == 1
    service.delete(state, "Old", preview)
    assert BatteryPackHistoryStore(history.path).observations == ()
    assert BatteryPackStore(tmp_path / "packs.json").association_for(
        state.fingerprint
    ).pack_id == "New"


def test_delete_preserves_history_recorded_after_log_reassignment(tmp_path):
    old_log = _bin(tmp_path, "old.bin", b"old")
    new_log = _bin(tmp_path, "new.bin", b"new")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(old_log), "Old")
    service.create_and_assign(service.lookup(new_log), "New")
    store = BatteryPackStore(tmp_path / "packs.json")
    store.associate(fingerprint_log(old_log), "New")
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    observation = _observation(source_sha256=fingerprint_log(old_log), pack_id="New")
    history.add_observations([observation])
    state = service.lookup(old_log)
    preview = service.preview_delete(state, "Old")
    assert preview.plan.log_fingerprints == preview.plan.observation_ids == ()
    service.delete(state, "Old", preview)
    assert BatteryPackHistoryStore(history.path).observations == (observation,)
    assert BatteryPackStore(store.path).association_for(fingerprint_log(old_log)).pack_id == "New"


def test_mixed_history_delete_retains_other_owner_and_report(tmp_path):
    selected = _bin(tmp_path, "packaging.bin", b"packaging")
    unrelated = _bin(tmp_path, "unrelated.bin", b"unrelated")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Packaging Test").state
    service.create_and_assign(service.lookup(unrelated), "Original")
    state = service.lookup(selected)
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    selected_observation = _observation(
        source_sha256=state.fingerprint, source_filename="packaging.bin",
        pack_id="Packaging Test",
    )
    retained_observation = _observation(
        source_sha256=state.fingerprint, source_filename="packaging.bin",
        pack_id="Original", battery_instance=1,
    )
    unrelated_observation = _observation(
        source_sha256=fingerprint_log(unrelated), source_filename="unrelated.bin",
        pack_id="Original",
    )
    history.add_observations([
        selected_observation, retained_observation, unrelated_observation,
    ])
    preview = service.preview_delete(state, "Packaging Test")
    assert preview.plan.log_fingerprints == (state.fingerprint,)
    assert preview.plan.observation_ids == (selected_observation.observation_id,)
    assert preview.plan.retained_history_owners == (
        (retained_observation.observation_id, "Original"),
    )
    service.delete(state, "Packaging Test", preview)

    store = BatteryPackStore(tmp_path / "packs.json")
    reloaded_history = BatteryPackHistoryStore(history.path)
    assert store.association_for(state.fingerprint).state is LogPackState.NOT_TRACKED
    assert store.association_for(fingerprint_log(unrelated)).pack_id == "Original"
    assert set(reloaded_history.observations) == {
        retained_observation, unrelated_observation,
    }
    assert set(pack_performance_observations(store, reloaded_history, "Original")) == {
        retained_observation, unrelated_observation,
    }
    report = BatteryPackPerformanceService(
        pack_store_path=store.path, history_store_path=history.path,
    ).report("Original").text
    assert "packaging.bin" in report
    assert "unrelated.bin" in report
    store.rename_pack("Original", "Renamed")
    renamed_store = BatteryPackStore(store.path)
    assert renamed_store.retained_history_owner_for(
        retained_observation.observation_id
    ) == "Renamed"
    assert "packaging.bin" in BatteryPackPerformanceService(
        pack_store_path=store.path, history_store_path=history.path,
    ).report("Renamed").text
    assert selected.read_bytes() == b"packaging"
    assert unrelated.read_bytes() == b"unrelated"


def test_mixed_history_rollback_restores_both_files(tmp_path, monkeypatch):
    selected = _bin(tmp_path, "selected.bin")
    other = _bin(tmp_path, "other.bin", b"other")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Packaging Test").state
    service.create_and_assign(service.lookup(other), "Original")
    state = service.lookup(selected)
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([
        _observation(source_sha256=state.fingerprint, pack_id="Packaging Test"),
        _observation(source_sha256=state.fingerprint, pack_id="Original", battery_instance=1),
    ])
    preview = service.preview_delete(state, "Packaging Test")
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes())
    original_save = BatteryPackStore._save

    def fail_after_write(self, *args, **kwargs):
        original_save(self, *args, **kwargs)
        if "Packaging Test" not in args[0]:
            raise OSError("late persistence failure")

    monkeypatch.setattr(BatteryPackStore, "_save", fail_after_write)
    with pytest.raises(OSError, match="late persistence failure"):
        service.delete(state, "Packaging Test", preview)
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes()) == before


def test_history_write_failure_leaves_pack_and_history_unchanged(
    tmp_path, monkeypatch,
):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Packaging Test").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([
        _observation(source_sha256=state.fingerprint, pack_id="Packaging Test"),
    ])
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes())
    original_save = BatteryPackHistoryStore._save

    def fail_after_write(self, observations):
        original_save(self, observations)
        raise OSError("late history persistence failure")

    monkeypatch.setattr(BatteryPackHistoryStore, "_save", fail_after_write)
    with pytest.raises(OSError, match="late history persistence failure"):
        service.delete(state, "Packaging Test", service.preview_delete(state, "Packaging Test"))
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes()) == before


def test_missing_historical_owner_blocks_with_actionable_reason(tmp_path):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Packaging Test").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([
        _observation(source_sha256=state.fingerprint, pack_id="Vanished"),
    ])
    before = ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes())
    with pytest.raises(BatteryPackStoreError, match="Restore that Pack ID or resolve"):
        service.preview_delete(state, "Packaging Test")
    assert ((tmp_path / "packs.json").read_bytes(), history.path.read_bytes()) == before


def test_delete_preview_error_is_shown_in_message_box(
    tmp_path, qt_app, make_window, monkeypatch,
):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Packaging Test").state
    BatteryPackHistoryStore(tmp_path / "history.json").add_observations([
        _observation(source_sha256=state.fingerprint, pack_id="Vanished"),
    ])
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_delete_combo.setCurrentText("Packaging Test")
    assert "Vanished" in window.pack_delete_preview_text.toPlainText()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    window.pack_delete_button.click()
    assert warnings[0][0] == "Delete Pack ID failed"
    assert "Restore that Pack ID" in warnings[0][1]


def test_delete_worker_error_is_shown_in_message_box(
    tmp_path, qt_app, make_window, monkeypatch,
):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(selected), "Packaging Test")
    before = (tmp_path / "packs.json").read_bytes()
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_delete_combo.setCurrentText("Packaging Test")
    monkeypatch.setattr(window, "_confirm_pack_deletion", lambda _preview: True)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    def fail_delete(_state, _pack_id, _preview):
        raise OSError("simulated deletion write failure")

    monkeypatch.setattr(service, "delete", fail_delete)
    window.pack_delete_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert warnings == [
        ("Delete Pack ID failed", "simulated deletion write failure"),
    ]
    assert "simulated deletion write failure" in window.report_for(
        "Battery Pack Management"
    ).toPlainText()
    assert (tmp_path / "packs.json").read_bytes() == before


def test_deleted_log_can_be_reassigned_and_history_recorded_again(tmp_path):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Mistake").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([_observation(source_sha256=state.fingerprint, pack_id="Mistake")])
    service.delete(state, "Mistake", service.preview_delete(state, "Mistake"))
    state = service.create_and_assign(service.lookup(selected), "Correct").state
    history = BatteryPackHistoryStore(history.path)
    assert history.add_observations([
        _observation(source_sha256=state.fingerprint, pack_id="Correct")
    ]) == 1
    assert history.observations[0].pack_id_at_ingest == "Correct"
    assert selected.read_bytes() == b"BIN evidence"


def test_real_delete_dialog_shows_impact_and_refreshes_gui(
    tmp_path, qt_app, make_window,
):
    selected = _bin(tmp_path, "selected.bin")
    service = _service(tmp_path)
    state = service.create_and_assign(service.lookup(selected), "Mistake").state
    history = BatteryPackHistoryStore(tmp_path / "history.json")
    history.add_observations([_observation(source_sha256=state.fingerprint, pack_id="Mistake")])
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.pack_delete_combo.setCurrentText("Mistake")
    seen = []

    def answer():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        seen.append((dialog.windowTitle(), dialog.text()))
        next(button for button in dialog.buttons() if button.text() == "Delete Pack ID").click()

    QTimer.singleShot(25, answer)
    window.pack_delete_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "1 associated BIN log" in seen[0][1]
    assert "1 battery history observation" in seen[0][1]
    assert "original BIN files untouched" in seen[0][1]
    assert window.pack_association_value.text() == "Not tracked"
    assert window.pack_delete_combo.findText("Mistake") == -1
    assert "Deleted Pack ID Mistake" in window.report_for(
        "Battery Pack Management"
    ).toPlainText()
    assert BatteryPackHistoryStore(history.path).observations == ()


def test_deleting_empty_archived_pack_preserves_other_pack(tmp_path):
    first = _bin(tmp_path, "first.bin", b"first")
    second = _bin(tmp_path, "second.bin", b"second")
    service = _service(tmp_path)
    service.create_and_assign(service.lookup(first), "Archived")
    service.create_and_assign(service.lookup(second), "Keep")
    store = BatteryPackStore(tmp_path / "packs.json")
    store.mark_not_tracked(fingerprint_log(first))
    store.archive_pack("Archived")
    state = service.lookup(second)
    preview = service.preview_delete(state, "Archived")
    assert preview.plan.log_fingerprints == preview.plan.observation_ids == ()
    service.delete(state, "Archived", preview)
    reloaded = BatteryPackStore(tmp_path / "packs.json")
    assert reloaded.pack_ids == ("Keep",)
    assert reloaded.association_for(fingerprint_log(second)).pack_id == "Keep"


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
    page_text = "\n".join(
        label.text()
        for label in window.analysis_tabs.currentWidget().findChildren(QLabel)
    )

    assert window.pack_selected_bin_value.text() == "No BIN selected"
    assert window.pack_association_value.text() == "Unseen"
    assert window.pack_assign_combo.count() == 1
    assert window.pack_assign_combo.currentText() == "— Select Pack ID —"
    assert window.pack_assign_combo.currentData() is None
    assert window.pack_rename_combo.currentText() == "— Select Pack ID —"
    assert window.pack_rename_combo.currentData() is None
    assert not window.pack_assign_button.isEnabled()
    assert not window.pack_create_button.isEnabled()
    assert not window.pack_rename_button.isEnabled()
    assert not window.pack_record_history_button.isEnabled()
    assert "Manage pack identities and log associations." in page_text
    assert (
        "Manage Pack IDs without a BIN. Select a BIN above to assign a pack or record history."
        in page_text
    )
    assert "Pack associations apply to the entire BIN log." in page_text
    assert (
        "Updates the Pack ID in every saved BIN association that uses it."
        in page_text
    )
    assert (
        "Adds supported AUTO takeoff data from this BIN to the assigned pack's "
        "history."
        in page_text
    )
    assert "Explicitly record supported AUTO takeoff evidence" not in page_text
    assert window.report_for("Battery Pack Management").toPlainText() == (
        "Persistent association loaded."
    )
    assert not (tmp_path / "packs.json").exists()
    assert not (tmp_path / "history.json").exists()


def test_pack_management_action_controls_remain_compact_and_ordered(
    tmp_path,
    qt_app,
    make_window,
):
    window = make_window(_service(tmp_path))
    window.show_analysis_tab("Battery Pack Management")
    qt_app.processEvents()

    assign_combo = window.pack_assign_combo
    assign_button = window.pack_assign_button
    rename_edit = window.pack_rename_edit
    rename_button = window.pack_rename_button
    rename_group = rename_button.parentWidget()
    history_button = window.pack_record_history_button

    assert assign_combo.maximumWidth() == 250
    assert assign_combo.width() <= 250
    assert assign_button.x() > assign_combo.x()
    assert rename_edit.minimumWidth() == 320
    assert rename_edit.width() >= 320
    assert rename_edit.isVisibleTo(window)
    assert rename_button.isVisibleTo(window)
    assert rename_button.height() >= rename_button.sizeHint().height()
    assert rename_button.width() < rename_group.width() / 2
    # Both the button and its bottom edge must remain inside the group,
    # rather than being painted off-screen by a compressed form row.
    assert rename_button.geometry().right() >= rename_group.contentsRect().right() - 30
    assert rename_button.geometry().bottom() <= rename_group.contentsRect().bottom()
    assert rename_button.mapToGlobal(rename_button.rect().topLeft()).y() < (
        history_button.mapToGlobal(history_button.rect().topLeft()).y()
    )


def test_lifecycle_controls_visible_by_default_and_scroll_on_small_window(
    tmp_path, qt_app, make_window
):
    window = make_window(_service(tmp_path))
    window.show_analysis_tab("Battery Pack Management")
    qt_app.processEvents()
    scroll = window.pack_controls_scroll
    viewport = scroll.viewport()
    for button in (
        window.pack_archive_button,
        window.pack_restore_button,
        window.pack_delete_button,
    ):
        top = button.mapTo(viewport, QPoint(0, 0)).y()
        assert 0 <= top
        assert top + button.height() <= viewport.height()

    window.resize(window.width(), 600)
    qt_app.processEvents()
    assert scroll.verticalScrollBar().maximum() > 0
    assert scroll.verticalScrollBar().isVisible()
    scroll.ensureWidgetVisible(window.pack_rename_button)
    qt_app.processEvents()
    rename = window.pack_rename_button
    assert rename.height() >= rename.sizeHint().height()
    assert rename.mapTo(viewport, QPoint(0, 0)).y() >= 0
    assert rename.mapTo(viewport, QPoint(0, rename.height())).y() <= viewport.height()


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

    assert not window.pack_assign_button.isEnabled()
    window.pack_assign_combo.setCurrentText("Pack A")
    assert window.pack_assign_button.isEnabled()
    window.pack_assign_button.click()
    window.pack_create_edit.setText("Pack B")
    window.pack_create_button.click()
    window.pack_rename_combo.setCurrentText("Pack A")
    window.pack_rename_edit.setText("Pack C")
    assert window.pack_rename_button.isEnabled()
    window.pack_rename_button.click()

    assert window._analysis_thread is None
    assert (tmp_path / "packs.json").read_bytes() == original

    window.set_selected_log(seed)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.pack_association_value.text() == "Tracked — Pack A"
    assert window.pack_assign_combo.currentData() is None
    assert window.pack_rename_combo.currentData() is None
    assert window.pack_record_history_button.isEnabled()
    window.pack_record_history_button.click()

    assert window._analysis_thread is None
    assert not (tmp_path / "history.json").exists()
    confirmation_text = "\n".join(message for _title, message in confirmations)
    assert "Source BIN: selected.bin" in confirmation_text
    assert "Current association: Unseen" in confirmation_text
    assert "Proposed Pack ID: Pack A" in confirmation_text
    assert "New Pack ID: Pack B" in confirmation_text
    assert "every saved BIN association" in confirmation_text
    assert "Source BIN: seed.bin" in confirmation_text
    assert "Tracked Pack ID: Pack A" in confirmation_text


def test_pack_selectors_reject_placeholder_and_retain_intentional_selection(
    tmp_path,
    qt_app,
    make_window,
    monkeypatch,
):
    service = _service(tmp_path)
    seed = _bin(tmp_path, "seed.bin", b"seed")
    selected = _bin(tmp_path, "selected.bin", b"selected")
    service.create_and_assign(service.lookup(seed), "Pack A")
    window = make_window(service)
    window.show_analysis_tab("Battery Pack Management")
    window.set_selected_log(selected)
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    confirmations = []
    monkeypatch.setattr(
        window,
        "_confirm_pack_action",
        lambda *args: confirmations.append(args) or True,
    )

    window.pack_rename_edit.setText("Pack B")
    assert window.pack_assign_combo.currentData() is None
    assert window.pack_rename_combo.currentData() is None
    assert not window.pack_assign_button.isEnabled()
    assert not window.pack_rename_button.isEnabled()
    window.assign_existing_pack()
    window.rename_pack()
    assert confirmations == []

    window.pack_assign_combo.setCurrentText("Pack A")
    window.pack_rename_combo.setCurrentText("Pack A")
    window._refresh_pack_management_view()
    assert window.pack_assign_combo.currentData() == "Pack A"
    assert window.pack_rename_combo.currentData() == "Pack A"
    assert window.pack_assign_button.isEnabled()
    assert window.pack_rename_button.isEnabled()


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
    history_store = SimpleNamespace(observations=())

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

    with pytest.raises(StalePackManagementStateError, match="associations changed"):
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
    assert window.pack_assign_combo.currentData() is None
    window.pack_assign_combo.setCurrentText("Pack A")
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
            "— Select Pack ID —",
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
