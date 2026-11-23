"""Explicit v2 Pack Management recording and stale-state regressions."""

import pandas as pd
import pytest
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_history_protection import journal_path
from core.battery_pack_history_v2 import BatteryPackHistoryV2Store
from core.battery_pack_store import BatteryPackStore, fingerprint_log
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.params import ParameterHistory
from test_battery_load_response import _bat
from test_battery_pack_history import _observation as v1_observation
from test_battery_pack_history_protection import _gui_adapter
from test_battery_pack_history_v2 import _observation as v2_observation
from test_battery_pack_history_v2_recorder import _recorder
from test_pilot_takeoff import _log as pilot_log

adapter = _gui_adapter()
BatteryPackManagementService = adapter.BatteryPackManagementService
StalePackManagementStateError = adapter.StalePackManagementStateError


def _service(tmp_path, log, *, on_read=None, recorder_factory=None):
    class Reader:
        def __init__(self, _path, config=None):
            pass

        def read(self):
            if on_read is not None:
                on_read()
            return log

    options = {"v2_recorder_factory": recorder_factory} if recorder_factory else {}
    return BatteryPackManagementService(
        pack_store_path=tmp_path / "packs.json",
        history_store_path=tmp_path / "v1.json",
        v2_history_store_path=tmp_path / "v2.json",
        reader_factory=Reader, **options,
    )


def _tracked(tmp_path, service):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"synthetic BIN")
    state = service.create_and_assign(service.lookup(source), "Pack A").state
    return source, state


def test_explicit_recording_replays_without_pack_or_v1_write(tmp_path):
    service = _service(tmp_path, pilot_log())
    source, state = _tracked(tmp_path, service)
    v1 = BatteryPackHistoryStore(tmp_path / "v1.json")
    pack_before = (tmp_path / "packs.json").read_bytes()
    assert not (tmp_path / "v2.json").exists()
    first = service.record_history_v2(state)
    assert first.observations_added == 2
    assert "flight.bin" in first.message and "Pack A" in first.message
    assert "v2" not in first.message
    v2_before = (tmp_path / "v2.json").read_bytes()
    second = service.record_history_v2(first.state)
    assert second.observations_added == 0
    assert (tmp_path / "v2.json").read_bytes() == v2_before
    assert (tmp_path / "packs.json").read_bytes() == pack_before
    assert not v1.path.exists()
    assert {row.flight_mode for row in BatteryPackHistoryV2Store(tmp_path / "v2.json").observations} == {"FBWA", "MANUAL"}
    assert fingerprint_log(source) == state.fingerprint


def test_service_records_auto_with_logged_gps_window_start(tmp_path):
    window = FlightWindow(1_500_000, 25_000_000)
    log = FlightLog(messages={
        "BAT": _bat(),
        "GPS": pd.DataFrame({"TimeUS": [window.start_us]}),
        "MODE": pd.DataFrame([{"TimeUS": 500_000, "ModeNum": 13},
                              {"TimeUS": 7_000_000, "ModeNum": 5}]),
        "MSG": pd.DataFrame([{"TimeUS": 900_000, "Message": "Triggered AUTO"}]),
    }, parameter_history=ParameterHistory({}), flights=[window])
    service = _service(tmp_path, log)
    _, state = _tracked(tmp_path, service)
    assert service.record_history_v2(state).observations_added == 1
    observation = BatteryPackHistoryV2Store(tmp_path / "v2.json").observations[0]
    assert observation.takeoff_type == observation.flight_mode == "AUTO"
    assert observation.logged_takeoff_us == window.start_us
    assert observation.load.t0_us != observation.logged_takeoff_us


def test_service_records_multiple_flights_and_bat_instances(tmp_path, monkeypatch):
    windows = [FlightWindow(4_000_000, 20_000_000),
               FlightWindow(24_000_000, 40_000_000)]
    log = FlightLog(messages={"GPS": pd.DataFrame(
        {"TimeUS": [window.start_us for window in windows]})}, flights=windows)
    recorder = _recorder(monkeypatch, ("MANUAL", "FBWA"))
    service = _service(tmp_path, log, recorder_factory=lambda _config: recorder)
    _, state = _tracked(tmp_path, service)
    assert service.record_history_v2(state).observations_added == 4
    observations = BatteryPackHistoryV2Store(tmp_path / "v2.json").observations
    assert {row.flight_number for row in observations} == {1, 2}
    assert {row.battery_instance for row in observations} == {0, 1}


@pytest.mark.parametrize("change", ["bin", "association", "revision", "v1", "v2"])
def test_decode_time_change_rejects_without_v2_write(tmp_path, change):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"synthetic BIN")

    def mutate():
        if change == "bin":
            source.write_bytes(b"changed BIN")
        elif change == "association":
            store = BatteryPackStore(tmp_path / "packs.json")
            store.create_and_associate("a" * 64, "Pack B")
            store.associate(fingerprint_log(source), "Pack B")
        elif change == "revision":
            BatteryPackStore(tmp_path / "packs.json").create_and_associate("a" * 64, "Pack B")
        else:
            (tmp_path / f"{change}.json").write_text('{"version": 99, "observations": {}}')

    service = _service(tmp_path, pilot_log(), on_read=mutate)
    _, state = _tracked(tmp_path, service)
    with pytest.raises((StalePackManagementStateError, ValueError)):
        service.record_history_v2(state)
    if change != "v2":
        assert not (tmp_path / "v2.json").exists()


@pytest.mark.parametrize("change", ["association", "revision", "v1", "v2"])
def test_empty_flight_decode_still_rechecks_state_before_success(tmp_path, change):
    snapshots = {}
    source = tmp_path / "flight.bin"
    source.write_bytes(b"empty-flight BIN")

    def snapshot():
        return tuple((path.read_bytes() if path.exists() else None)
                     for path in (tmp_path / "packs.json", tmp_path / "v1.json",
                                  tmp_path / "v2.json"))

    def mutate():
        if change == "association":
            store = BatteryPackStore(tmp_path / "packs.json")
            store.create_and_associate("b" * 64, "Pack B")
            store.associate(fingerprint_log(source), "Pack B")
        elif change == "revision":
            BatteryPackStore(tmp_path / "packs.json").create_and_associate("b" * 64, "Pack B")
        elif change == "v1":
            BatteryPackHistoryStore(tmp_path / "v1.json").add_observations([
                v1_observation(source_sha256="b" * 64)])
        else:
            BatteryPackHistoryV2Store(tmp_path / "v2.json").add_observations([
                v2_observation(source="b" * 64)])
        snapshots["after_decode_mutation"] = snapshot()

    service = _service(tmp_path, FlightLog(flights=[]), on_read=mutate)
    _, state = _tracked(tmp_path, service)
    with pytest.raises(StalePackManagementStateError):
        service.record_history_v2(state)
    assert snapshot() == snapshots["after_decode_mutation"]


def test_unchanged_empty_flight_returns_zero_without_creating_v2(tmp_path):
    service = _service(tmp_path, FlightLog(flights=[]))
    _, state = _tracked(tmp_path, service)
    pack_before = (tmp_path / "packs.json").read_bytes()
    result = service.record_history_v2(state)
    assert result.observations_added == 0
    assert not result.changed
    assert (tmp_path / "packs.json").read_bytes() == pack_before
    assert not (tmp_path / "v1.json").exists()
    assert not (tmp_path / "v2.json").exists()


def test_untracked_and_changed_source_rejected_without_history(tmp_path):
    service = _service(tmp_path, pilot_log())
    source = tmp_path / "flight.bin"
    source.write_bytes(b"synthetic BIN")
    with pytest.raises(StalePackManagementStateError, match="tracked Pack ID"):
        service.record_history_v2(service.lookup(source))
    state = service.create_and_assign(service.lookup(source), "Pack A").state
    BatteryPackStore(tmp_path / "packs.json").mark_not_tracked(state.fingerprint)
    with pytest.raises(StalePackManagementStateError, match="tracked Pack ID"):
        service.record_history_v2(service.lookup(source))
    state = service.assign_existing(service.lookup(source), "Pack A").state
    source.write_bytes(b"changed")
    with pytest.raises(StalePackManagementStateError, match="content changed"):
        service.record_history_v2(state)
    assert not (tmp_path / "v2.json").exists()


def test_unresolved_deletion_journal_blocks_v2_recording(tmp_path):
    service = _service(tmp_path, pilot_log())
    _, state = _tracked(tmp_path, service)
    journal_path(tmp_path / "packs.json").mkdir()
    before = (tmp_path / "packs.json").read_bytes()
    with pytest.raises(ValueError, match="recovery failed"):
        service.record_history_v2(state)
    assert (tmp_path / "packs.json").read_bytes() == before
    assert not (tmp_path / "v2.json").exists()


def test_rename_replay_retains_first_ingest_owner(tmp_path):
    service = _service(tmp_path, pilot_log())
    _, state = _tracked(tmp_path, service)
    recorded = service.record_history_v2(state)
    renamed = service.rename(recorded.state, "Pack A", "Pack B")
    assert service.record_history_v2(renamed.state).observations_added == 0
    assert {row.pack_id_at_ingest for row in
            BatteryPackHistoryV2Store(tmp_path / "v2.json").observations} == {"Pack A"}


def test_conflicting_analysis_rejects_batch_without_rewriting_stores(tmp_path):
    log = pilot_log()
    service = _service(tmp_path, log)
    _, state = _tracked(tmp_path, service)
    first = service.record_history_v2(state)
    before = ((tmp_path / "packs.json").read_bytes(),
              (tmp_path / "v2.json").read_bytes())
    bat = log.messages["BAT"]
    bat.loc[bat["TimeUS"].between(5_000_000, 10_000_000), "Volt"] = 13
    with pytest.raises(ValueError, match="Conflicting evidence"):
        service.record_history_v2(first.state)
    assert ((tmp_path / "packs.json").read_bytes(),
            (tmp_path / "v2.json").read_bytes()) == before
    assert not (tmp_path / "v1.json").exists()


@pytest.mark.parametrize("phase", ["recorder", "persistence"])
def test_recorder_or_v2_persistence_failure_preserves_other_stores(
        tmp_path, phase, monkeypatch):
    service = _service(tmp_path, pilot_log())
    _, state = _tracked(tmp_path, service)
    before = (tmp_path / "packs.json").read_bytes()
    if phase == "recorder":
        from core.battery_pack_history_v2_recorder import BatteryPackHistoryV2Recorder

        monkeypatch.setattr(BatteryPackHistoryV2Recorder, "record",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("recorder failure")))
    else:
        monkeypatch.setattr(BatteryPackHistoryV2Store, "_save",
                            lambda *_args: (_ for _ in ()).throw(OSError("write failure")))
    with pytest.raises(OSError, match="failure"):
        service.record_history_v2(state)
    assert (tmp_path / "packs.json").read_bytes() == before
    assert not (tmp_path / "v1.json").exists()
    assert not (tmp_path / "v2.json").exists()
