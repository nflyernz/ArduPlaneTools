"""Focused tests for persistent physical battery Pack ID metadata."""

from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from analyses.battery import (
    BatteryAnalysisPresentation,
    BatteryPackManagementPresentation,
)
from core.battery_pack_store import (
    BatteryPackStore,
    BatteryPackStoreError,
    BatteryPackStoreFormatError,
    LogPackState,
    fingerprint_log,
)


def _inputs(monkeypatch, *responses):
    """Provide deterministic answers to battery-pack prompts."""
    values = iter(responses)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(values))


def _log(path: Path, content: bytes = b"same DataFlash content") -> Path:
    """Create one compact stand-in BIN with controlled content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_fingerprint_uses_content_not_filename_or_path(tmp_path):
    """Moved or renamed identical content retains one SHA-256 identity."""
    first = _log(tmp_path / "first" / "log_1.bin")
    renamed = _log(tmp_path / "elsewhere" / "renamed.BIN")
    different = _log(tmp_path / "future" / "log_1.bin", b"different content")

    first_fingerprint = fingerprint_log(first)

    assert len(first_fingerprint) == 64
    assert first_fingerprint == fingerprint_log(renamed)
    assert first_fingerprint != fingerprint_log(different)


def test_tracked_associations_and_known_pack_ids_round_trip(tmp_path):
    """Known IDs and tracked source associations survive store reload."""
    path = tmp_path / "Data" / "battery_packs.json"
    first_fingerprint = "1" * 64
    second_fingerprint = "2" * 64
    store = BatteryPackStore(path)

    store.create_and_associate(first_fingerprint, "Pack 1")
    store.associate(second_fingerprint, "Pack 1")
    reloaded = BatteryPackStore(path)

    assert reloaded.pack_ids == ("Pack 1",)
    assert reloaded.association_for(first_fingerprint).state is LogPackState.TRACKED
    assert reloaded.association_for(first_fingerprint).pack_id == "Pack 1"
    assert reloaded.association_for(second_fingerprint).pack_id == "Pack 1"


def test_version_one_store_loads_and_archiving_retains_associations(tmp_path):
    path = tmp_path / "packs.json"
    fingerprint = "a" * 64
    path.write_text(json.dumps({"version": 1, "pack_ids": ["Pack 1"],
                                "log_associations": {fingerprint: {
                                    "state": "tracked", "pack_id": "Pack 1"}}}))
    store = BatteryPackStore(path)
    assert store.active_pack_ids == ("Pack 1",)
    store.archive_pack("Pack 1")
    reloaded = BatteryPackStore(path)
    assert reloaded.pack_ids == ("Pack 1",)
    assert reloaded.active_pack_ids == ()
    assert reloaded.archived_pack_ids == ("Pack 1",)
    assert reloaded.association_for(fingerprint).pack_id == "Pack 1"
    with pytest.raises(BatteryPackStoreError, match="Unknown Pack ID"):
        reloaded.associate("b" * 64, "Pack 1")
    reloaded.restore_pack("Pack 1")
    assert BatteryPackStore(path).active_pack_ids == ("Pack 1",)


def test_delete_requires_no_associations_or_historical_observations(tmp_path):
    path = tmp_path / "packs.json"
    fingerprint = "a" * 64
    store = BatteryPackStore(path)
    store.create_and_associate(fingerprint, "Pack 1")
    history = SimpleNamespace(observations=())
    with pytest.raises(BatteryPackStoreError, match="log associations"):
        store.delete_pack("Pack 1", history)
    store.mark_not_tracked(fingerprint)
    history.observations = (SimpleNamespace(pack_id_at_ingest="Pack 1",
                                            source_sha256=fingerprint),)
    with pytest.raises(BatteryPackStoreError, match="historical observations"):
        store.delete_pack("Pack 1", history)
    assert BatteryPackStore(path).pack_ids == ("Pack 1",)
    store.delete_pack("Pack 1", SimpleNamespace(observations=()))
    assert BatteryPackStore(path).pack_ids == ()


def test_explicit_not_tracked_state_round_trips_without_synthetic_pack(tmp_path):
    """Declining tracking is durable and creates no placeholder Pack ID."""
    path = tmp_path / "Data" / "battery_packs.json"
    fingerprint = "3" * 64
    store = BatteryPackStore(path)

    store.mark_not_tracked(fingerprint)
    reloaded = BatteryPackStore(path)
    association = reloaded.association_for(fingerprint)

    assert reloaded.pack_ids == ()
    assert association.state is LogPackState.NOT_TRACKED
    assert association.pack_id is None


def test_malformed_store_is_reported_and_not_overwritten(tmp_path):
    """Invalid existing JSON raises explicitly and remains byte-for-byte intact."""
    path = tmp_path / "Data" / "battery_packs.json"
    path.parent.mkdir()
    malformed = b'{"version": 1, "pack_ids": '
    path.write_bytes(malformed)

    with pytest.raises(BatteryPackStoreFormatError, match="Unable to read"):
        BatteryPackStore(path)

    assert path.read_bytes() == malformed


def test_cancel_leaves_unseen_log_unpersisted(monkeypatch, tmp_path):
    """Cancelling an unseen log creates no store and records no decision."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    log_path = _log(tmp_path / "flight.bin")
    store = BatteryPackStore(store_path)
    presentation = BatteryAnalysisPresentation(config=object(), pack_store=store)
    _inputs(monkeypatch, "0")

    assert presentation._resolve_pack_id(log_path) == (False, None)
    assert not store_path.exists()
    assert store.association_for(fingerprint_log(log_path)).state is (
        LogPackState.UNSEEN
    )


def test_unseen_log_can_create_pack_then_resolves_without_reprompt(
    monkeypatch,
    tmp_path,
):
    """A created association is reused for identical content without input."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    log_path = _log(tmp_path / "flight.bin")
    presentation = BatteryAnalysisPresentation(
        config=object(),
        pack_store=BatteryPackStore(store_path),
    )
    _inputs(monkeypatch, "1", "LiPo-A")

    assert presentation._resolve_pack_id(log_path) == (True, "LiPo-A")

    reloaded_presentation = BatteryAnalysisPresentation(
        config=object(),
        pack_store=BatteryPackStore(store_path),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": pytest.fail("known association prompted again"),
    )
    assert reloaded_presentation._resolve_pack_id(log_path) == (True, "LiPo-A")


def test_moved_identical_log_resolves_association_without_reprompt(
    monkeypatch,
    tmp_path,
):
    """A persisted association follows identical BIN content to another path."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    original = _log(tmp_path / "original" / "flight.bin")
    moved = _log(tmp_path / "archive" / "renamed.bin")
    presentation = BatteryAnalysisPresentation(
        config=object(),
        pack_store=BatteryPackStore(store_path),
    )
    _inputs(monkeypatch, "1", "Pack 1")
    assert presentation._resolve_pack_id(original) == (True, "Pack 1")

    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": pytest.fail("identical moved log prompted again"),
    )
    assert presentation._resolve_pack_id(moved) == (True, "Pack 1")


def test_same_filename_with_different_content_remains_unseen(monkeypatch, tmp_path):
    """A filename cannot transfer Pack ID ownership to different BIN content."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    log_path = _log(tmp_path / "flight.bin", b"first flight")
    store = BatteryPackStore(store_path)
    presentation = BatteryAnalysisPresentation(config=object(), pack_store=store)
    first_fingerprint = fingerprint_log(log_path)
    _inputs(monkeypatch, "1", "Pack 1")
    assert presentation._resolve_pack_id(log_path) == (True, "Pack 1")

    _log(log_path, b"different flight in the same filename")
    second_fingerprint = fingerprint_log(log_path)
    _inputs(monkeypatch, "0")

    assert presentation._resolve_pack_id(log_path) == (False, None)
    assert store.association_for(first_fingerprint).pack_id == "Pack 1"
    assert store.association_for(second_fingerprint).state is LogPackState.UNSEEN


def test_one_presentation_does_not_carry_interactive_pack_to_another_log(
    monkeypatch,
    tmp_path,
):
    """Resolving one BIN does not silently assign its Pack ID to a later BIN."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    first_log = _log(tmp_path / "first.bin", b"first flight")
    second_log = _log(tmp_path / "second.bin", b"second flight")
    store = BatteryPackStore(store_path)
    presentation = BatteryAnalysisPresentation(config=object(), pack_store=store)
    _inputs(monkeypatch, "1", "Pack 1")
    assert presentation._resolve_pack_id(first_log) == (True, "Pack 1")

    _inputs(monkeypatch, "0")
    assert presentation._resolve_pack_id(second_log) == (False, None)
    assert presentation.pack_id is None
    assert store.association_for(fingerprint_log(second_log)).state is (
        LogPackState.UNSEEN
    )


def test_unseen_log_can_select_existing_or_persist_not_tracked(
    monkeypatch,
    tmp_path,
):
    """Both remaining unseen-log decisions persist and suppress later prompts."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    seed_log = _log(tmp_path / "seed.bin", b"seed")
    selected_log = _log(tmp_path / "selected.bin", b"selected")
    untracked_log = _log(tmp_path / "untracked.bin", b"untracked")
    store = BatteryPackStore(store_path)
    store.create_and_associate(fingerprint_log(seed_log), "Pack 1")
    presentation = BatteryAnalysisPresentation(config=object(), pack_store=store)

    _inputs(monkeypatch, "1", "1")
    assert presentation._resolve_pack_id(selected_log) == (True, "Pack 1")

    _inputs(monkeypatch, "3")
    assert presentation._resolve_pack_id(untracked_log) == (True, None)

    reloaded = BatteryPackStore(store_path)
    assert reloaded.association_for(fingerprint_log(selected_log)).pack_id == "Pack 1"
    assert reloaded.association_for(fingerprint_log(untracked_log)).state is (
        LogPackState.NOT_TRACKED
    )
    repeated = BatteryAnalysisPresentation(config=object(), pack_store=reloaded)
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": pytest.fail("not-tracked log prompted again"),
    )
    assert repeated._resolve_pack_id(untracked_log) == (True, None)

    assert reloaded.pack_ids == ("Pack 1",)


def test_invalid_new_pack_ids_are_rejected_then_valid_decisions_persist(
    monkeypatch,
    tmp_path,
    capsys,
):
    """Whitespace and duplicate IDs do not prevent a later valid choice."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    first_log = _log(tmp_path / "first.bin", b"first flight")
    second_log = _log(tmp_path / "second.bin", b"second flight")
    store = BatteryPackStore(store_path)
    presentation = BatteryAnalysisPresentation(config=object(), pack_store=store)

    _inputs(monkeypatch, "1", "   ", "1", "Pack 1")
    assert presentation._resolve_pack_id(first_log) == (True, "Pack 1")
    assert "Pack ID must be a non-empty string." in capsys.readouterr().out

    _inputs(monkeypatch, "2", " Pack 1 ", "2", "Pack 2")
    assert presentation._resolve_pack_id(second_log) == (True, "Pack 2")
    assert "Pack ID already exists: Pack 1" in capsys.readouterr().out

    reloaded = BatteryPackStore(store_path)
    assert reloaded.pack_ids == ("Pack 1", "Pack 2")
    assert reloaded.association_for(fingerprint_log(first_log)).pack_id == "Pack 1"
    assert reloaded.association_for(fingerprint_log(second_log)).pack_id == "Pack 2"


@pytest.mark.parametrize(
    "malformed",
    [
        b'{"version": 1, "pack_ids": ',
        b'{"version": 1, "pack_ids": [], "log_associations": []}\n',
    ],
    ids=["invalid-json", "invalid-schema"],
)
def test_malformed_store_allows_analysis_without_overwriting_it(
    monkeypatch,
    tmp_path,
    capsys,
    malformed,
):
    """Presentation reports unreadable persistence and continues without metadata."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    store_path.parent.mkdir()
    store_path.write_bytes(malformed)
    log_path = _log(tmp_path / "flight.bin")
    presentation = BatteryAnalysisPresentation(config=object())
    monkeypatch.setattr(
        "analyses.battery.BatteryPackStore",
        lambda: BatteryPackStore(store_path),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt="": pytest.fail("malformed store should not prompt"),
    )

    assert presentation._resolve_pack_id(log_path) == (True, None)
    output = capsys.readouterr().out
    assert "Battery pack tracking unavailable:" in output
    assert "Persistent pack data was not changed." in output
    assert store_path.read_bytes() == malformed


@pytest.mark.parametrize(
    "responses",
    [
        ("1", "Pack 1"),
        ("2",),
    ],
    ids=["create-pack", "continue-without-tracking"],
)
def test_write_failure_does_not_change_store_state(
    monkeypatch,
    tmp_path,
    capsys,
    responses,
):
    """A failed decision save remains unseen in memory and on disk."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    log_path = _log(tmp_path / "flight.bin")
    fingerprint = fingerprint_log(log_path)
    store = BatteryPackStore(store_path)
    presentation = BatteryAnalysisPresentation(config=object(), pack_store=store)
    _inputs(monkeypatch, *responses)
    monkeypatch.setattr(
        "core.battery_pack_store.os.replace",
        lambda _source, _destination: (_ for _ in ()).throw(
            OSError("simulated write failure")
        ),
    )

    assert presentation._resolve_pack_id(log_path) == (True, None)
    output = capsys.readouterr().out
    assert "Unable to save battery pack decision: simulated write failure" in output
    assert "persistent data was not changed" in output
    assert store.pack_ids == ()
    assert store.association_for(fingerprint).state is LogPackState.UNSEEN
    assert not store_path.exists()


def test_explicit_constructor_pack_id_bypasses_persistent_resolution(
    monkeypatch,
    tmp_path,
):
    """Caller-supplied Pack ID remains compatible and avoids interactive lookup."""
    log_path = _log(tmp_path / "flight.bin")
    presentation = BatteryAnalysisPresentation(
        pack_id="Pack supplied by caller",
        config=object(),
    )
    monkeypatch.setattr("analyses.battery.select_log_input", lambda: [log_path])
    monkeypatch.setattr(
        presentation,
        "_resolve_pack_id",
        lambda _path: pytest.fail("explicit Pack ID triggered persistence resolution"),
    )

    class EmptyFlightReader:
        """Minimal reader result sufficient to end after Pack ID resolution."""

        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def read():
            return type("EmptyFlightLog", (), {"flights": []})()

    monkeypatch.setattr("analyses.battery.FlightReader", EmptyFlightReader)

    presentation.run()



def test_rename_pack_updates_all_matching_associations_atomically(tmp_path):
    """Renaming one Pack ID updates every matching log and preserves others."""
    path = tmp_path / "Data" / "battery_packs.json"
    first = "1" * 64
    second = "2" * 64
    unrelated = "3" * 64
    not_tracked = "4" * 64

    store = BatteryPackStore(path)
    store.create_and_associate(first, "Pack 1")
    store.associate(second, "Pack 1")
    store.create_and_associate(unrelated, "Pack 2")
    store.mark_not_tracked(not_tracked)

    store.rename_pack(" Pack 1 ", " Renamed Pack ")

    reloaded = BatteryPackStore(path)

    assert reloaded.pack_ids == ("Renamed Pack", "Pack 2")
    assert reloaded.association_for(first).pack_id == "Renamed Pack"
    assert reloaded.association_for(second).pack_id == "Renamed Pack"
    assert reloaded.association_for(unrelated).pack_id == "Pack 2"
    assert reloaded.association_for(not_tracked).state is LogPackState.NOT_TRACKED


@pytest.mark.parametrize(
    ("old_pack_id", "new_pack_id", "message"),
    [
        ("Missing", "Pack 3", "Unknown Pack ID: Missing"),
        ("Pack 1", "Pack 2", "Pack ID already exists: Pack 2"),
    ],
    ids=["unknown-source", "duplicate-destination"],
)
def test_invalid_rename_leaves_store_unchanged(
    tmp_path,
    old_pack_id,
    new_pack_id,
    message,
):
    """Invalid rename requests change neither durable nor in-memory state."""
    path = tmp_path / "Data" / "battery_packs.json"
    first = "1" * 64
    second = "2" * 64

    store = BatteryPackStore(path)
    store.create_and_associate(first, "Pack 1")
    store.create_and_associate(second, "Pack 2")

    original_bytes = path.read_bytes()

    with pytest.raises(BatteryPackStoreError, match=message):
        store.rename_pack(old_pack_id, new_pack_id)

    assert path.read_bytes() == original_bytes
    assert store.pack_ids == ("Pack 1", "Pack 2")
    assert store.association_for(first).pack_id == "Pack 1"
    assert store.association_for(second).pack_id == "Pack 2"


def test_pack_management_same_name_is_reported_as_unchanged(
    monkeypatch,
    tmp_path,
    capsys,
):
    """Entering the current Pack ID is a harmless no-op."""
    path = tmp_path / "Data" / "battery_packs.json"
    fingerprint = "1" * 64

    store = BatteryPackStore(path)
    store.create_and_associate(fingerprint, "Pack 1")

    presentation = BatteryPackManagementPresentation(pack_store=store)
    _inputs(monkeypatch, "1", "1", " Pack 1 ", "0")

    presentation.run()

    output = capsys.readouterr().out

    assert "Pack ID unchanged." in output
    assert store.pack_ids == ("Pack 1",)
    assert store.association_for(fingerprint).pack_id == "Pack 1"


def test_pack_management_renames_persisted_identity(
    monkeypatch,
    tmp_path,
    capsys,
):
    """Management UI renames the selected physical pack and its log ownership."""
    path = tmp_path / "Data" / "battery_packs.json"
    lipo = "1" * 64
    lithium_ion = "2" * 64

    store = BatteryPackStore(path)
    store.create_and_associate(lipo, "LIPO-3900-01")
    store.create_and_associate(lithium_ion, "505-P1")

    presentation = BatteryPackManagementPresentation(pack_store=store)
    _inputs(monkeypatch, "1", "2", "50S-P1", "0")

    presentation.run()

    output = capsys.readouterr().out
    reloaded = BatteryPackStore(path)

    assert "Renamed Pack ID: 505-P1 -> 50S-P1" in output
    assert reloaded.pack_ids == ("LIPO-3900-01", "50S-P1")
    assert reloaded.association_for(lipo).pack_id == "LIPO-3900-01"
    assert reloaded.association_for(lithium_ion).pack_id == "50S-P1"


def test_pack_management_rename_write_failure_preserves_store(
    monkeypatch,
    tmp_path,
    capsys,
):
    """A failed atomic rename leaves disk and live store state unchanged."""
    path = tmp_path / "Data" / "battery_packs.json"
    fingerprint = "1" * 64

    store = BatteryPackStore(path)
    store.create_and_associate(fingerprint, "Pack 1")
    original_bytes = path.read_bytes()

    monkeypatch.setattr(
        "core.battery_pack_store.os.replace",
        lambda _source, _destination: (_ for _ in ()).throw(
            OSError("simulated rename failure")
        ),
    )

    presentation = BatteryPackManagementPresentation(pack_store=store)
    _inputs(monkeypatch, "1", "1", "Renamed Pack", "0")

    presentation.run()

    output = capsys.readouterr().out

    assert "Unable to rename Battery Pack ID: simulated rename failure" in output
    assert "Persistent pack data was not changed." in output
    assert path.read_bytes() == original_bytes
    assert store.pack_ids == ("Pack 1",)
    assert store.association_for(fingerprint).pack_id == "Pack 1"



def test_pack_management_dispatches_log_reassignment(
    monkeypatch,
    tmp_path,
):
    """Management menu option 2 reaches the log-reassignment workflow."""
    store = BatteryPackStore(tmp_path / "Data" / "battery_packs.json")
    presentation = BatteryPackManagementPresentation(pack_store=store)

    called = []

    monkeypatch.setattr(
        presentation,
        "_change_log_pack_assignment",
        lambda selected_store: called.append(selected_store),
    )
    _inputs(monkeypatch, "2", "0")

    presentation.run()

    assert called == [store]


def test_log_assignment_can_change_to_existing_pack(
    monkeypatch,
    tmp_path,
):
    """One source BIN can be reassigned to another existing physical pack."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    first_log = _log(tmp_path / "first.bin", b"first")
    second_log = _log(tmp_path / "second.bin", b"second")

    first_fingerprint = fingerprint_log(first_log)
    second_fingerprint = fingerprint_log(second_log)

    store = BatteryPackStore(store_path)
    store.create_and_associate(first_fingerprint, "Pack 1")
    store.create_and_associate(second_fingerprint, "Pack 2")

    presentation = BatteryPackManagementPresentation(pack_store=store)

    monkeypatch.setattr(
        "analyses.battery.select_log_input",
        lambda: [first_log],
    )
    _inputs(monkeypatch, "1", "2")

    presentation._change_log_pack_assignment(store)

    reloaded = BatteryPackStore(store_path)

    assert reloaded.pack_ids == ("Pack 1", "Pack 2")
    assert reloaded.association_for(first_fingerprint).pack_id == "Pack 2"
    assert reloaded.association_for(second_fingerprint).pack_id == "Pack 2"


def test_log_assignment_can_create_new_pack(
    monkeypatch,
    tmp_path,
):
    """Reassignment may create a new physical Pack ID for the selected BIN."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    log_path = _log(tmp_path / "flight.bin")
    fingerprint = fingerprint_log(log_path)

    store = BatteryPackStore(store_path)
    store.create_and_associate(fingerprint, "Pack 1")

    presentation = BatteryPackManagementPresentation(pack_store=store)

    monkeypatch.setattr(
        "analyses.battery.select_log_input",
        lambda: [log_path],
    )
    _inputs(monkeypatch, "2", "Pack 2")

    presentation._change_log_pack_assignment(store)

    reloaded = BatteryPackStore(store_path)

    assert reloaded.pack_ids == ("Pack 1", "Pack 2")
    assert reloaded.association_for(fingerprint).pack_id == "Pack 2"


def test_log_assignment_same_existing_pack_is_no_op(
    monkeypatch,
    tmp_path,
    capsys,
):
    """Selecting the current physical Pack ID does not rewrite ownership."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    log_path = _log(tmp_path / "flight.bin")
    fingerprint = fingerprint_log(log_path)

    store = BatteryPackStore(store_path)
    store.create_and_associate(fingerprint, "Pack 1")
    original_bytes = store_path.read_bytes()

    presentation = BatteryPackManagementPresentation(pack_store=store)

    monkeypatch.setattr(
        "analyses.battery.select_log_input",
        lambda: [log_path],
    )
    _inputs(monkeypatch, "1", "1")

    presentation._change_log_pack_assignment(store)

    output = capsys.readouterr().out

    assert "Pack assignment unchanged." in output
    assert store_path.read_bytes() == original_bytes
    assert store.association_for(fingerprint).pack_id == "Pack 1"


def test_log_reassignment_write_failure_preserves_existing_assignment(
    monkeypatch,
    tmp_path,
    capsys,
):
    """A failed reassignment changes neither durable nor in-memory ownership."""
    store_path = tmp_path / "Data" / "battery_packs.json"
    first_log = _log(tmp_path / "first.bin", b"first")
    second_log = _log(tmp_path / "second.bin", b"second")

    first_fingerprint = fingerprint_log(first_log)
    second_fingerprint = fingerprint_log(second_log)

    store = BatteryPackStore(store_path)
    store.create_and_associate(first_fingerprint, "Pack 1")
    store.create_and_associate(second_fingerprint, "Pack 2")
    original_bytes = store_path.read_bytes()

    monkeypatch.setattr(
        "analyses.battery.select_log_input",
        lambda: [first_log],
    )
    monkeypatch.setattr(
        "core.battery_pack_store.os.replace",
        lambda _source, _destination: (_ for _ in ()).throw(
            OSError("simulated reassignment failure")
        ),
    )

    presentation = BatteryPackManagementPresentation(pack_store=store)
    _inputs(monkeypatch, "1", "2")

    presentation._change_log_pack_assignment(store)

    output = capsys.readouterr().out

    assert "Unable to change Pack ID assignment: simulated reassignment failure" in output
    assert "Persistent pack data was not changed." in output
    assert store_path.read_bytes() == original_bytes
    assert store.association_for(first_fingerprint).pack_id == "Pack 1"
    assert store.association_for(second_fingerprint).pack_id == "Pack 2"
