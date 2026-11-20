"""Synthetic v2 schema, identity, storage and v1 compatibility regressions."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from core.battery_pack_history import (
    BatteryPackHistoryFormatError,
    BatteryPackHistoryStore,
)
from core.battery_pack_history_v2 import (
    SEMANTICS,
    BatteryPackHistoryV2Store,
    BatteryPackObservationV2,
    LoadEvidenceV2,
    PlateauEvidenceV2,
    physical_event_id_for,
    v2_observation_id_for,
)
from core.battery_pack_store import BatteryPackStore
from core.gps_time import format_utc_milliseconds, gps_week_time_to_utc
from test_battery_pack_history import _observation as v1_observation


def _load(*, strict=False):
    return LoadEvidenceV2(
        "qualified", 4_900_000, "qualified", 20.0, 16.0,
        "qualified", 8_000_000, 25.0, 14.0, 22.0,
        "qualified" if strict else "unavailable",
        16.0 if strict else None, 2.0 if strict else None,
        2.0 if strict else None,
        "qualified", 9_000_000, 15.0, 4.0,
        () if strict else ("Low-current voltage baseline unavailable.",),
    )


def _plateau(*, qualified=True):
    if not qualified:
        return PlateauEvidenceV2("unavailable", *([None] * 10),
                                 "No sufficiently recent pre-onset plateau.")
    return PlateauEvidenceV2("qualified", 3_700_000, 4_700_000, 16.0, 5.0,
                             5_300_000, 6_300_000, 14.5, 21.0, 1.5, 16.0, None)


def _observation(*, mode="FBWA", timestamp=5_000_000, strict=False,
                 source="a" * 64, pack="Pack A"):
    event_id = physical_event_id_for(
        source_sha256=source, battery_instance=0, flight_start_us=4_000_000,
        flight_end_us=10_000_000, logged_takeoff_us=timestamp)
    return BatteryPackObservationV2(
        2, SEMANTICS, event_id, v2_observation_id_for(event_id), source,
        "flight.bin", pack, 0, 1, 4_000_000, 10_000_000,
        "AUTO" if mode == "AUTO" else "PILOT_CONTROLLED", mode,
        timestamp, None, None, None, None, None, None, True,
        _load(strict=strict), _plateau(),
    )


@pytest.mark.parametrize("mode", ["AUTO", "MANUAL", "FBWA"])
def test_round_trip_all_takeoff_modes_and_nullable_strict_drop(mode):
    original = _observation(mode=mode)
    assert original.load.qualified_voltage_drop_v is None
    assert BatteryPackObservationV2.from_dict(original.to_dict()) == original
    assert original.plateau.observed_voltage_change_v == 1.5


def test_physical_identity_excludes_analysis_boundaries_and_classification():
    original = _observation()
    changed = replace(original, load=replace(original.load, t0_us=4_800_000,
                                              t1_us=7_000_000),
                      plateau=_plateau(qualified=False))
    changed.validate()
    assert changed.physical_event_id == original.physical_event_id
    assert changed.observation_id == original.observation_id
    assert _observation(mode="AUTO").physical_event_id == original.physical_event_id
    assert _observation(timestamp=5_000_001).physical_event_id != original.physical_event_id


def test_isolated_v2_store_is_deterministic_idempotent_and_rejects_conflicts(tmp_path):
    path = tmp_path / "history_v2.json"
    store = BatteryPackHistoryV2Store(path)
    first = _observation()
    second = _observation(source="b" * 64, strict=True)
    assert store.add_observations([second, first, first]) == 2
    original = path.read_bytes()
    assert store.add_observations([first, second]) == 0
    assert path.read_bytes() == original
    assert BatteryPackHistoryV2Store(path).observations == store.observations
    with pytest.raises(ValueError, match="Conflicting evidence"):
        store.add_observations([_observation(source="c" * 64),
                                replace(first, load=replace(first.load, peak_current_a=26.0))])
    assert path.read_bytes() == original


def test_replay_ignores_only_mutable_ingest_provenance_and_keeps_original(tmp_path):
    path = tmp_path / "history_v2.json"
    store = BatteryPackHistoryV2Store(path)
    original = _observation()
    store.add_observations([original])
    initial_bytes = path.read_bytes()
    replay = replace(original, source_filename="renamed.bin", pack_id_at_ingest="Pack B")
    assert store.add_observations([replay]) == 0
    assert store.observations == (original,)
    assert path.read_bytes() == initial_bytes
    assert BatteryPackHistoryV2Store(path).observations == (original,)
    with pytest.raises(ValueError, match="Conflicting evidence"):
        store.add_observations([replace(replay, flight_mode="MANUAL")])
    assert path.read_bytes() == initial_bytes


def test_mixed_batch_replay_and_new_record_is_atomic_on_conflict(tmp_path):
    path = tmp_path / "history_v2.json"
    store = BatteryPackHistoryV2Store(path)
    original = _observation()
    store.add_observations([original])
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Conflicting evidence"):
        store.add_observations([
            replace(original, pack_id_at_ingest="Pack B"),
            _observation(source="c" * 64),
            replace(original, plateau=replace(original.plateau, loaded_voltage_v=14.0,
                                               observed_voltage_change_v=2.0)),
        ])
    assert path.read_bytes() == before
    assert store.observations == (original,)
    assert store.add_observations([
        replace(original, source_filename="renamed.bin"),
        _observation(source="c" * 64),
    ]) == 1
    assert next(item for item in store.observations
                if item.observation_id == original.observation_id) == original


@pytest.mark.parametrize("change", [
    lambda d: d.update(analysis_semantics_version="battery-load-v1"),
    lambda d: d.update(observation_schema_version=1),
    lambda d: d.update(physical_event_id="0" * 64),
    lambda d: d.update(observation_id="0" * 64),
    lambda d: d.update(source_sha256="bad"),
    lambda d: d.update(battery_instance=-1),
    lambda d: d.update(flight_end_us=4_000_000),
    lambda d: d.update(flight_mode="AUTO"),
    lambda d: d.update(physical_contact_inferred=False),
    lambda d: d["load"].update(reference_current_a=float("nan")),
    lambda d: d["load"].update(t1_us=4_000_000),
    lambda d: d["load"].update(qualified_voltage_drop_v=2.0),
    lambda d: d["load"].update(limitations=[]),
    lambda d: d["plateau"].update(observed_voltage_change_v=99.0),
    lambda d: d["plateau"].update(loaded_end_us=11_000_000),
    lambda d: d["plateau"].update(status="unavailable"),
    lambda d: d.update(extra="unexpected"),
])
def test_corrupt_or_confused_v2_record_rejected(change):
    data = _observation().to_dict()
    change(data)
    with pytest.raises(BatteryPackHistoryFormatError):
        BatteryPackObservationV2.from_dict(data)


def test_unqualified_plateau_needs_reason_and_no_numbers():
    observation = replace(_observation(), plateau=_plateau(qualified=False))
    observation.validate()
    assert observation.plateau.observed_voltage_change_v is None
    with pytest.raises(BatteryPackHistoryFormatError):
        replace(observation.plateau, observed_voltage_change_v=1.0).validate()


@pytest.mark.parametrize("change", [
    lambda o: replace(o, plateau=replace(o.plateau, pre_start_us=4_699_999)),
    lambda o: replace(o, plateau=replace(o.plateau, loaded_end_us=5_300_001)),
    lambda o: replace(o, plateau=replace(o.plateau, pre_end_us=4_000_000)),
    lambda o: replace(o, plateau=replace(o.plateau, loaded_start_us=11_000_000,
                                         loaded_end_us=12_000_000)),
    lambda o: replace(o, plateau=replace(o.plateau, loaded_current_a=5.5,
                                         current_change_a=0.5)),
    lambda o: replace(o, plateau=replace(o.plateau, loaded_current_a=13.0,
                                         current_change_a=8.0)),
    lambda o: replace(o, load=replace(o.load, reference_status="unavailable",
                                      reference_current_a=None, threshold_current_a=None,
                                      t1_status="unavailable", t1_us=None,
                                      recovery_status="unavailable", recovery_time_us=None,
                                      recovery_voltage_v=None, recovery_current_a=None)),
])
def test_qualified_plateau_requires_self_consistent_evidence(change):
    with pytest.raises(BatteryPackHistoryFormatError):
        change(_observation()).validate()


def test_qualified_recovery_requires_a_later_qualified_t1():
    observation = _observation()
    with pytest.raises(BatteryPackHistoryFormatError):
        replace(observation, load=replace(observation.load,
                                          recovery_time_us=6_000_000)).validate()
    with pytest.raises(BatteryPackHistoryFormatError):
        replace(observation, load=replace(observation.load,
                                          t1_status="unavailable", t1_us=None)).validate()


def test_partial_load_can_keep_raw_extrema_without_inventing_t0_or_drop():
    load = LoadEvidenceV2(
        "unavailable", None, "unavailable", None, None, "unavailable", None,
        24.0, 14.2, 22.0, "unavailable", None, None, None,
        "unavailable", None, None, None, ("BAT baseline unavailable.",),
    )
    observation = replace(_observation(), load=load, plateau=_plateau(qualified=False))
    observation.validate()
    assert BatteryPackObservationV2.from_dict(observation.to_dict()) == observation
    assert observation.load.qualified_voltage_drop_v is None


def test_utc_provenance_is_canonical_and_matches_logged_takeoff():
    observation = _observation()
    recorded = format_utc_milliseconds(gps_week_time_to_utc(2500, 100_000, 18)
                                        + timedelta(microseconds=1_000_000))
    with_gps = replace(observation, recorded_at_utc=recorded,
                       gps_anchor_week=2500, gps_anchor_week_ms=100_000,
                       gps_anchor_time_us=4_000_000, gps_instance=0,
                       gps_utc_offset_seconds=18)
    with_gps.validate()
    assert BatteryPackObservationV2.from_dict(with_gps.to_dict()) == with_gps
    with pytest.raises(BatteryPackHistoryFormatError):
        replace(with_gps, recorded_at_utc="2020-01-01T00:00:00.000Z").validate()


def test_v1_store_and_ids_unchanged_and_v2_envelope_rejected(tmp_path):
    old = v1_observation()
    v1_path = tmp_path / "history_v1.json"
    v1_store = BatteryPackHistoryStore(v1_path)
    assert v1_store.add_observations([old]) == 1
    v1_bytes = v1_path.read_bytes()
    assert BatteryPackHistoryStore(v1_path).observations == (old,)
    with pytest.raises(BatteryPackHistoryFormatError):
        BatteryPackHistoryV2Store(v1_path)
    v2_path = tmp_path / "history_v2.json"
    BatteryPackHistoryV2Store(v2_path).add_observations([_observation()])
    with pytest.raises(BatteryPackHistoryFormatError):
        BatteryPackHistoryStore(v2_path)
    assert v1_path.read_bytes() == v1_bytes
    assert old.event_key != _observation().physical_event_id


def test_corrupt_file_cannot_overwrite_valid_history(tmp_path):
    path = tmp_path / "history_v2.json"
    store = BatteryPackHistoryV2Store(path)
    store.add_observations([_observation()])
    valid = path.read_bytes()
    raw = json.loads(valid)
    raw["observations"][next(iter(raw["observations"]))]["plateau"]["pre_voltage_v"] = "broken"
    path.write_text(json.dumps(raw))
    damaged = path.read_bytes()
    with pytest.raises(BatteryPackHistoryFormatError):
        BatteryPackHistoryV2Store(path)
    assert path.read_bytes() == damaged
    assert valid != damaged


def test_pack_ownership_rename_archive_and_deletion_plan_with_explicit_v2_store(tmp_path):
    packs = BatteryPackStore(tmp_path / "packs.json")
    history = BatteryPackHistoryV2Store(tmp_path / "history_v2.json")
    observation = _observation()
    packs.create_and_associate(observation.source_sha256, "Pack A")
    history.add_observations([observation])
    assert packs.history_owner_for(observation) == "Pack A"
    packs.rename_pack("Pack A", "Pack B")
    packs.archive_pack("Pack B")
    assert packs.history_owner_for(observation) == "Pack B"
    assert packs.deletion_plan("Pack B", history).observation_ids == (observation.observation_id,)
    assert "Pack B" not in packs.unused_pack_ids(history)
    plan = packs.delete_pack("Pack B", history)
    assert plan.observation_ids == (observation.observation_id,)
    assert BatteryPackHistoryV2Store(history.path).observations == ()
