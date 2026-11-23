"""Synthetic coordinated v1/v2 Pack History deletion regressions."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from analyses.battery import BatteryPackManagementPresentation
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_history_protection import (
    CoordinatedHistory,
    DeletionOutcomeUncertain,
    journal_path,
    recover_pending_deletion,
)
from core.battery_pack_history_v2 import BatteryPackHistoryV2Store
from core.battery_pack_store import BatteryPackStore, BatteryPackStoreError
from test_battery_pack_history import _observation as v1_observation
from test_battery_pack_history_v2 import _observation as v2_observation


def _gui_adapter():
    """Load the Qt-independent adapter without importing the GUI package."""
    name = "stage2a_pack_management_adapter"
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parent / "gui" / "pack_management_adapter.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _setup(tmp_path, *, v1=False, v2=False):
    pack_path = tmp_path / "packs.json"
    v1_path = tmp_path / "history.json"
    v2_path = tmp_path / "battery_pack_history_v2.json"
    pack = BatteryPackStore(pack_path)
    pack.create_and_associate("a" * 64, "Original")
    pack.create_and_associate("b" * 64, "Other")
    first = v1_observation(source_sha256="a" * 64, pack_id="Original")
    second = v2_observation(source="a" * 64, pack="Original")
    other = v2_observation(source="b" * 64, pack="Other")
    if v1:
        BatteryPackHistoryStore(v1_path).add_observations([first])
    if v2:
        BatteryPackHistoryV2Store(v2_path).add_observations([second, other])
    return pack, v1_path, v2_path, first, second, other


@pytest.mark.parametrize("v1,v2", [(False, False), (True, False), (False, True), (True, True)])
def test_deletion_keeps_other_pack_and_original_bin(tmp_path, v1, v2):
    pack, v1_path, v2_path, first, second, other = _setup(tmp_path, v1=v1, v2=v2)
    original_bin = tmp_path / "original.BIN"
    original_bin.write_bytes(b"real source is never part of the transaction")
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    plan = pack.deletion_plan("Original", history)
    assert plan.observation_ids == ((first.observation_id,) if v1 else ())
    assert plan.v2_observation_ids == ((second.observation_id,) if v2 else ())
    assert "Original" not in pack.unused_pack_ids(history)
    pack.delete_pack("Original", history, plan)
    assert BatteryPackStore(pack.path).pack_ids == ("Other",)
    assert BatteryPackHistoryStore(v1_path).observations == ()
    assert BatteryPackHistoryV2Store(v2_path).observations == ((other,) if v2 else ())
    assert v1_path.exists() == v1
    assert v2_path.exists() == v2
    assert original_bin.read_bytes() == b"real source is never part of the transaction"
    assert not journal_path(pack.path).exists()


def test_foreign_coordinated_history_cannot_delete_overlapping_pack_id(tmp_path):
    first, first_v1, first_v2, _, _, _ = _setup(tmp_path / "first", v1=True, v2=True)
    second, second_v1, second_v2, _, _, _ = _setup(tmp_path / "second", v1=True, v2=True)
    paths = (first.path, first_v1, first_v2, second.path, second_v1, second_v2)
    before = tuple(path.read_bytes() for path in paths)
    foreign = CoordinatedHistory(second.path, second_v1, second_v2)

    with pytest.raises(BatteryPackStoreError, match="different Pack Store"):
        first.delete_pack("Original", foreign)
    with pytest.raises(BatteryPackStoreError, match="different Pack Store"):
        first.deletion_plan("Original", foreign)
    with pytest.raises(BatteryPackStoreError, match="different Pack Store"):
        first.unused_pack_ids(foreign)

    assert tuple(path.read_bytes() for path in paths) == before
    assert first.pack_ids == second.pack_ids == ("Original", "Other")
    assert not journal_path(first.path).exists()
    assert not journal_path(second.path).exists()


def test_matching_custom_pack_path_accepts_resolved_equivalent(tmp_path):
    pack, v1_path, v2_path, _, second, other = _setup(tmp_path / "custom", v2=True)
    equivalent = pack.path.parent / ".." / pack.path.parent.name / pack.path.name
    history = CoordinatedHistory(equivalent, v1_path, v2_path)
    plan = pack.deletion_plan("Original", history)
    assert plan.v2_observation_ids == (second.observation_id,)
    pack.delete_pack("Original", history, plan)
    assert BatteryPackStore(pack.path).pack_ids == ("Other",)
    assert BatteryPackHistoryV2Store(v2_path).observations == (other,)


def test_rename_archive_and_reassignment_preserve_v2_historical_owner(tmp_path):
    pack, v1_path, v2_path, _, second, _ = _setup(tmp_path, v2=True)
    pack.rename_pack("Original", "Renamed")
    pack.archive_pack("Renamed")
    pack.associate("a" * 64, "Other")
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    assert pack.history_owner_for(second) == "Renamed"
    assert pack.deletion_plan("Renamed", history).v2_observation_ids == (second.observation_id,)
    assert pack.deletion_plan("Other", history).v2_observation_ids != (second.observation_id,)
    assert pack.deletion_plan("Other", history).retained_history_owners == (
        (second.observation_id, "Renamed"),
    )
    assert "Renamed" not in pack.unused_pack_ids(history)
    pack.delete_pack("Other", history)
    assert BatteryPackHistoryV2Store(v2_path).observations == (second,)
    assert BatteryPackStore(pack.path).history_owner_for(second) == "Renamed"


def test_v2_history_alone_blocks_unused_pack_eligibility(tmp_path):
    pack, v1_path, v2_path, _, second, _ = _setup(tmp_path, v2=True)
    pack.mark_not_tracked("a" * 64)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    assert "Original" not in pack.unused_pack_ids(history)
    assert pack.deletion_plan("Original", history).v2_observation_ids == (
        second.observation_id,
    )


def test_legacy_v1_delete_cannot_orphan_v2_after_rename_and_reassignment(tmp_path):
    pack, v1_path, v2_path, _, second, other = _setup(tmp_path, v2=True)
    pack.rename_pack("Original", "Renamed")
    pack.archive_pack("Renamed")
    pack.associate("a" * 64, "Other")
    v1_only = BatteryPackHistoryStore(v1_path)
    assert pack.deletion_plan("Renamed", v1_only).v2_observation_ids == (
        second.observation_id,
    )
    assert "Renamed" not in pack.unused_pack_ids(v1_only)
    pack.delete_pack("Renamed", v1_only)
    assert BatteryPackStore(pack.path).pack_ids == ("Other",)
    assert BatteryPackHistoryV2Store(v2_path).observations == (other,)


def test_legacy_v1_delete_blocks_corrupt_sibling_v2(tmp_path):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    v2_path.write_text("{")
    with pytest.raises(ValueError):
        pack.delete_pack("Original", BatteryPackHistoryStore(v1_path))
    assert "Original" in BatteryPackStore(pack.path).pack_ids


@pytest.mark.parametrize("which", ["v1", "v2"])
def test_stale_history_revision_blocks_confirmed_deletion(tmp_path, which):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    plan = pack.deletion_plan("Original", history)
    path = v1_path if which == "v1" else v2_path
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(BatteryPackStoreError, match="changed after confirmation"):
        pack.delete_pack("Original", CoordinatedHistory(pack.path, v1_path, v2_path), plan)
    assert "Original" in BatteryPackStore(pack.path).pack_ids


@pytest.mark.parametrize("target", ["v1", "v2", "pack"])
def test_write_failure_restores_disk_and_memory(tmp_path, monkeypatch, target):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    before = tuple(path.read_bytes() for path in (pack.path, v1_path, v2_path))
    obj = {"v1": history.v1, "v2": history.v2, "pack": pack}[target]
    original = obj._save

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError(f"failed {target} write")

    monkeypatch.setattr(obj, "_save", fail_after_write)
    with pytest.raises(OSError, match=f"failed {target} write"):
        pack.delete_pack("Original", history)
    assert tuple(path.read_bytes() for path in (pack.path, v1_path, v2_path)) == before
    assert pack.pack_ids == ("Original", "Other")
    assert len(history.v1.observations) == 1
    assert len(history.v2.observations) == 2
    assert not journal_path(pack.path).exists()


def test_failed_rollback_retains_journal_for_later_recovery(tmp_path, monkeypatch):
    import core.battery_pack_history_protection as protection

    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    before = tuple(path.read_bytes() for path in (pack.path, v1_path, v2_path))
    original_save = history.v2._save
    original_recover = protection.recover_pending_deletion

    def fail_write(*args):
        original_save(*args)
        raise OSError("v2 failed")

    def fail_recovery(*_args, **_kwargs):
        raise BatteryPackStoreError("rollback unavailable")

    monkeypatch.setattr(history.v2, "_save", fail_write)
    monkeypatch.setattr(protection, "recover_pending_deletion", fail_recovery)
    with pytest.raises(BatteryPackStoreError, match="rollback unavailable"):
        pack.delete_pack("Original", history)
    assert journal_path(pack.path).exists()
    monkeypatch.setattr(protection, "recover_pending_deletion", original_recover)
    recover_pending_deletion(pack.path, v1_path, v2_path)
    assert tuple(path.read_bytes() for path in (pack.path, v1_path, v2_path)) == before


@pytest.mark.parametrize("fault", ["before_marker", "after_marker", "after_marker_sync"])
def test_commit_boundary_fault_reports_actual_transaction_state(tmp_path, monkeypatch, fault):
    import core.battery_pack_history_protection as protection

    pack, v1_path, v2_path, _, _, other = _setup(tmp_path, v1=True, v2=True)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    paths = (pack.path, v1_path, v2_path)
    before = tuple(path.read_bytes() for path in paths)
    original_replace = protection.os.replace
    original_sync = protection._directory_sync
    sync_count = 0

    def fault_replace(source, destination):
        if destination == journal_path(pack.path) / "manifest.json":
            data = json.loads(Path(source).read_text())
            if data["state"] == "committed":
                if fault == "before_marker":
                    raise OSError("before committed marker")
                original_replace(source, destination)
                if fault == "after_marker":
                    raise OSError("after committed marker")
                return
        original_replace(source, destination)

    def fault_sync(path):
        nonlocal sync_count
        if path == journal_path(pack.path):
            sync_count += 1
            if fault == "after_marker_sync" and sync_count == 3:
                original_sync(path)
                raise OSError("after committed marker sync")
        original_sync(path)

    monkeypatch.setattr(protection.os, "replace", fault_replace)
    monkeypatch.setattr(protection, "_directory_sync", fault_sync)
    if fault == "before_marker":
        with pytest.raises(OSError, match="before committed marker"):
            pack.delete_pack("Original", history)
        assert tuple(path.read_bytes() for path in paths) == before
        assert pack.pack_ids == ("Original", "Other")
        assert history.v2.observations == BatteryPackHistoryV2Store(v2_path).observations
    else:
        with pytest.raises(DeletionOutcomeUncertain, match="committed marker is visible"):
            pack.delete_pack("Original", history)
        assert BatteryPackStore(pack.path).pack_ids == ("Other",)
        assert BatteryPackHistoryV2Store(v2_path).observations == (other,)
        assert journal_path(pack.path).exists()
        monkeypatch.setattr(protection.os, "replace", original_replace)
        monkeypatch.setattr(protection, "_directory_sync", original_sync)
        assert recover_pending_deletion(*paths)
        assert BatteryPackStore(pack.path).pack_ids == ("Other",)


def test_precommit_directory_sync_failure_rolls_back_all_stores(tmp_path, monkeypatch):
    import core.battery_pack_history_protection as protection

    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    paths = (pack.path, v1_path, v2_path)
    before = tuple(path.read_bytes() for path in paths)
    original_sync = protection._directory_sync
    journal = journal_path(pack.path)
    fired = False

    def fail_after_pack_sync(path):
        nonlocal fired
        original_sync(path)
        if (not fired and path == pack.path.parent and journal.exists()
                and pack.pack_ids[0] != "Original"):
            fired = True
            raise OSError("precommit parent sync failed")

    monkeypatch.setattr(protection, "_directory_sync", fail_after_pack_sync)
    with pytest.raises(OSError, match="precommit parent sync failed"):
        pack.delete_pack("Original", history)
    assert tuple(path.read_bytes() for path in paths) == before
    assert pack.pack_ids == ("Original", "Other")
    assert len(history.v1.observations) == 1
    assert len(history.v2.observations) == 2


@pytest.mark.parametrize("fault", ["rename", "parent_sync", "partial_remove"])
def test_interrupted_completed_cleanup_does_not_block_management(tmp_path, monkeypatch, fault):
    import core.battery_pack_history_protection as protection

    pack, v1_path, v2_path, _, _, other = _setup(tmp_path, v2=True)
    original_rmtree = protection.shutil.rmtree
    original_replace = protection.os.replace
    original_sync = protection._directory_sync

    def interrupt_rename(source, destination):
        if source == journal_path(pack.path) and fault == "rename":
            raise OSError("retirement rename failed")
        return original_replace(source, destination)

    def interrupt_parent_sync(path):
        if (path == journal_path(pack.path).parent and fault == "parent_sync"
                and not journal_path(pack.path).exists()):
            raise OSError("retirement parent sync failed")
        return original_sync(path)

    def interrupt_cleanup(path, *args, **kwargs):
        if ".completed-" in str(path) and fault == "partial_remove":
            (Path(path) / "manifest.json").unlink()
            raise OSError("interrupted cleanup")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(protection.os, "replace", interrupt_rename)
    monkeypatch.setattr(protection, "_directory_sync", interrupt_parent_sync)
    monkeypatch.setattr(protection.shutil, "rmtree", interrupt_cleanup)
    pack.delete_pack("Original", CoordinatedHistory(pack.path, v1_path, v2_path))
    if fault == "rename":
        assert journal_path(pack.path).exists()
    else:
        assert not journal_path(pack.path).exists()
        assert list(tmp_path.glob(f"{journal_path(pack.path).name}.completed-*"))
    assert BatteryPackStore(pack.path).pack_ids == ("Other",)
    assert BatteryPackHistoryV2Store(v2_path).observations == (other,)
    monkeypatch.setattr(protection.os, "replace", original_replace)
    monkeypatch.setattr(protection, "_directory_sync", original_sync)
    assert CoordinatedHistory(pack.path, v1_path, v2_path).v2.observations == (other,)


@pytest.mark.parametrize("raw", ["[]", "null", '"text"', "0", "{}",
                                  '{"version": 1, "paths": [], "state": "prepared", "revisions": "bad"}'])
def test_malformed_manifest_types_raise_managed_error_and_retain_journal(tmp_path, raw):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    journal = journal_path(pack.path)
    journal.mkdir()
    (journal / "manifest.json").write_text(raw)
    with pytest.raises(BatteryPackStoreError, match="recovery failed"):
        recover_pending_deletion(pack.path, v1_path, v2_path)
    assert journal.exists()


def test_damaged_backup_blocks_recovery_and_retains_journal(tmp_path):
    from core.battery_pack_history_protection import _prepare_journal

    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v2=True)
    journal, _ = _prepare_journal((pack.path, v1_path, v2_path))
    (journal / "2.backup").write_text("damaged")
    with pytest.raises(BatteryPackStoreError, match="backup does not match"):
        recover_pending_deletion(pack.path, v1_path, v2_path)
    assert journal.exists()


def test_modified_manifest_cannot_claim_existing_files_were_absent(tmp_path):
    from core.battery_pack_history_protection import _prepare_journal

    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v2=True)
    original = pack.path.read_bytes()
    journal, _ = _prepare_journal((pack.path, v1_path, v2_path))
    manifest_path = journal / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["revisions"] = ["missing", "missing", "missing"]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BatteryPackStoreError, match="Invalid deletion journal manifest"):
        recover_pending_deletion(pack.path, v1_path, v2_path)
    assert pack.path.read_bytes() == original
    assert journal.exists()


def test_absent_history_files_stay_absent_after_failed_pack_write(tmp_path, monkeypatch):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    history = CoordinatedHistory(pack.path, v1_path, v2_path)
    original_bytes = pack.path.read_bytes()
    original_save = pack._save

    def fail_pack(*args, **kwargs):
        original_save(*args, **kwargs)
        raise OSError("pack write failed")

    monkeypatch.setattr(pack, "_save", fail_pack)
    with pytest.raises(OSError, match="pack write failed"):
        pack.delete_pack("Original", history)
    assert pack.path.read_bytes() == original_bytes
    assert not v1_path.exists() and not v2_path.exists()
    assert pack.pack_ids == ("Original", "Other")


def test_duplicate_store_paths_are_rejected(tmp_path):
    pack, v1_path, _, _, _, _ = _setup(tmp_path)
    with pytest.raises(BatteryPackStoreError, match="distinct"):
        CoordinatedHistory(pack.path, v1_path, v1_path)


def test_broken_v2_symlink_is_not_treated_as_empty_history(tmp_path):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    v2_path.symlink_to(tmp_path / "missing-target.json")
    with pytest.raises(BatteryPackStoreError, match="symbolic links"):
        CoordinatedHistory(pack.path, v1_path, v2_path)


def test_incomplete_journal_fails_closed_before_any_write(tmp_path):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    original_bytes = pack.path.read_bytes()
    journal_path(pack.path).mkdir()
    with pytest.raises(BatteryPackStoreError, match="recovery failed"):
        CoordinatedHistory(pack.path, v1_path, v2_path)
    assert pack.path.read_bytes() == original_bytes
    assert journal_path(pack.path).exists()
    with pytest.raises(BatteryPackStoreError, match="recovery failed"):
        pack.delete_pack("Original", BatteryPackHistoryStore(v1_path))
    assert pack.path.read_bytes() == original_bytes


def test_interrupted_transaction_recovers_before_gui_lookup(tmp_path):
    from core.battery_pack_history_protection import _prepare_journal

    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    paths = (pack.path, v1_path, v2_path)
    before = tuple(path.read_bytes() for path in paths)
    _prepare_journal(paths)
    v1_path.write_text('{"interrupted": true}')
    recovered = CoordinatedHistory(pack.path, v1_path, v2_path)
    assert len(recovered.v1.observations) == 1
    assert tuple(path.read_bytes() for path in paths) == before
    assert not journal_path(pack.path).exists()


def test_terminal_reloads_injected_store_after_recovery(tmp_path, monkeypatch):
    from core.battery_pack_history_protection import _prepare_journal

    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    original_ids = pack.pack_ids
    _prepare_journal((pack.path, v1_path, v2_path))
    pack._pack_ids = ["Other"]  # Simulate a stale injected object after interruption.
    assert pack.pack_ids == ("Other",)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")
    BatteryPackManagementPresentation(pack, v1_path, v2_path).run()
    assert pack.pack_ids == original_ids


@pytest.mark.parametrize("bad", ["malformed", "unsupported", "directory"])
def test_gui_management_fails_closed_on_invalid_v2(tmp_path, bad):
    BatteryPackManagementService = _gui_adapter().BatteryPackManagementService
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    if bad == "malformed":
        v2_path.write_text("{")
    elif bad == "unsupported":
        v2_path.write_text(json.dumps({"version": 999, "observations": {}}))
    else:
        v2_path.mkdir()
    service = BatteryPackManagementService(pack_store_path=pack.path,
                                           history_store_path=v1_path,
                                           v2_history_store_path=v2_path)
    with pytest.raises((ValueError, OSError)):
        service.lookup_packs()
    assert "Original" in BatteryPackStore(pack.path).pack_ids


def test_gui_preview_counts_v1_and_v2_and_rejects_stale_v2(tmp_path):
    adapter = _gui_adapter()
    BatteryPackManagementService = adapter.BatteryPackManagementService
    StalePackManagementStateError = adapter.StalePackManagementStateError
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    service = BatteryPackManagementService(pack_store_path=pack.path,
                                           history_store_path=v1_path,
                                           v2_history_store_path=v2_path)
    state = service.lookup_packs()
    preview = service.preview_delete(state, "Original")
    assert len(preview.plan.observation_ids) == len(preview.plan.v2_observation_ids) == 1
    assert preview.v2_history_revision
    v2_path.write_bytes(v2_path.read_bytes() + b" ")
    with pytest.raises(StalePackManagementStateError):
        service.delete(state, "Original", preview)


def test_terminal_deletion_prompt_names_both_versions(tmp_path, monkeypatch):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path, v1=True, v2=True)
    prompts = []
    answers = iter(["5", "1", "no", "0"])

    def answer(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    BatteryPackManagementPresentation(pack, v1_path, v2_path).run()
    assert any("1 v1 and 1 v2" in prompt for prompt in prompts)
    assert "Original" in BatteryPackStore(pack.path).pack_ids


def test_terminal_confirmed_deletion_removes_both_versions(tmp_path, monkeypatch):
    pack, v1_path, v2_path, _, _, other = _setup(tmp_path, v1=True, v2=True)
    answers = iter(["5", "1", "yes", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    BatteryPackManagementPresentation(pack, v1_path, v2_path).run()
    assert BatteryPackStore(pack.path).pack_ids == ("Other",)
    assert BatteryPackHistoryStore(v1_path).observations == ()
    assert BatteryPackHistoryV2Store(v2_path).observations == (other,)


def test_terminal_blocks_rename_when_v2_is_malformed(tmp_path, monkeypatch, capsys):
    pack, v1_path, v2_path, _, _, _ = _setup(tmp_path)
    v2_path.write_text("{")
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("menu must not open"))
    BatteryPackManagementPresentation(pack, v1_path, v2_path).run()
    assert "management unavailable" in capsys.readouterr().out
    assert BatteryPackStore(pack.path).pack_ids == ("Original", "Other")
