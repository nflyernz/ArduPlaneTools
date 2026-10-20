"""Tests for explicit legacy persistent-data migration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import core.data_migration as migration_module
from core.battery_pack_history import (
    ANALYSIS_SEMANTICS_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    BatteryPackHistoryStore,
    BatteryPackObservation,
    event_key_for,
    observation_id_for,
)
from core.battery_pack_store import BatteryPackStore, LogPackState
from core.data_migration import DataMigrationError, migrate_persistent_data
from core.gps_time import format_utc_milliseconds, gps_week_time_to_utc
from core.range_walk import LandmarkMarker, WalkSettings
from core.range_walk_history import (
    RangeWalkHistoryStore,
    fingerprint_csv,
)
from migrate_data import main


BASE = datetime(2026, 10, 19, 15, 24, 21)
FINGERPRINT = "1" * 64


@dataclass(frozen=True)
class _Baseline:
    source_path: Path
    label: str
    antenna: str
    landmark_names: tuple[str, ...]
    turnaround: str
    settings: WalkSettings
    candidates: tuple[LandmarkMarker, ...]
    candidate_numbers: tuple[int, ...]
    landmarks: tuple[LandmarkMarker, ...]
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime
    source_sha256: str


@dataclass(frozen=True)
class _AdditionalWalk:
    source_path: Path
    parent_baseline_id: str
    label: str
    antenna: str
    settings: WalkSettings
    candidates: tuple[LandmarkMarker, ...]
    candidate_numbers: tuple[int | None, ...]
    landmarks: tuple[LandmarkMarker | None, ...]
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime
    source_sha256: str


def _observation() -> BatteryPackObservation:
    identity = {
        "source_sha256": FINGERPRINT,
        "battery_instance": 0,
        "flight_start_us": 1_000_000,
        "flight_end_us": 5_000_000,
        "event_type": "TAKEOFF",
        "takeoff_type": "AUTO",
        "event_start_us": 2_000_000,
        "event_end_us": 3_000_000,
    }
    event_key = event_key_for(**identity)
    return BatteryPackObservation(
        event_key=event_key,
        observation_id=observation_id_for(event_key, ANALYSIS_SEMANTICS_VERSION),
        observation_schema_version=OBSERVATION_SCHEMA_VERSION,
        analysis_semantics_version=ANALYSIS_SEMANTICS_VERSION,
        pack_id_at_ingest="Pack A",
        source_sha256=FINGERPRINT,
        source_filename="flight.bin",
        firmware="ArduPlane V4.7.0",
        recorded_at_utc=format_utc_milliseconds(
            gps_week_time_to_utc(2000, 18_000, 18) + timedelta(seconds=1)
        ),
        gps_anchor_week=2000,
        gps_anchor_week_ms=18_000,
        gps_anchor_time_us=1_000_000,
        gps_instance=0,
        gps_utc_offset_seconds=18,
        flight_number=1,
        flight_start_us=1_000_000,
        flight_end_us=5_000_000,
        battery_instance=0,
        event_type="TAKEOFF",
        takeoff_type="AUTO",
        event_start_us=2_000_000,
        event_end_us=3_000_000,
        event_duration_s=1.0,
        capacity_used_mah=100.0,
        pre_load_voltage_v=16.0,
        minimum_loaded_voltage_v=14.5,
        peak_current_a=20.0,
        average_current_a=18.0,
        current_at_minimum_voltage_a=19.0,
        maximum_throttle_pct=100.0,
        average_throttle_pct=95.0,
        recovery_time_us=4_000_000,
        voltage_after_recovery_v=15.0,
        voltage_sag_v=1.5,
        voltage_recovery_v=0.5,
        low_voltage_margin_v=1.3,
        critical_voltage_margin_v=1.7,
        configuration_lookup_time_us=1_000_000,
        configured_capacity_mah=5000.0,
        configured_low_voltage_v=13.2,
        configured_critical_voltage_v=12.8,
        configured_failsafe_voltage_source=0.0,
        configuration_warnings=("historical context",),
    )


def _create_source(tmp_path: Path) -> tuple[Path, str, str, str]:
    source = tmp_path / "legacy" / "Data"
    pack_store = BatteryPackStore(source / "battery_packs.json")
    pack_store.create_and_associate(FINGERPRINT, "Pack A")
    observation = _observation()
    BatteryPackHistoryStore(source / "battery_pack_history.json").add_observations(
        [observation]
    )

    original_csv = tmp_path / "walk.csv"
    original_csv.write_text("Date,Time,Ele,RQly\n2026-10-19,15:24:21,2,100\n")
    markers = tuple(
        LandmarkMarker(
            BASE + timedelta(seconds=2 + index * 6),
            BASE + timedelta(seconds=5 + index * 6),
            30,
        )
        for index in range(5)
    )
    baseline = _Baseline(
        source_path=original_csv.resolve(),
        label="October 19 Walk 1",
        antenna="Vertical receiver antenna",
        landmark_names=("Gate", "Tree", "Fence", "Shed", "Turnaround"),
        turnaround="Turnaround",
        settings=WalkSettings("100 mW", "250 Hz", "2.4 GHz", "Off"),
        candidates=markers,
        candidate_numbers=(1, 2, 3, 4, 5),
        landmarks=markers,
        direction_used="higher",
        direction_assessment="Auto selected higher from sustained holds.",
        recording_start=BASE,
        recording_end=BASE + timedelta(seconds=32),
        source_sha256=fingerprint_csv(original_csv),
    )
    range_store = RangeWalkHistoryStore(
        source / "range_walk_history.json",
        source / "range_walk_csv",
    )
    baseline_record = range_store.add_baseline(baseline)

    additional_csv = tmp_path / "walk-2.csv"
    additional_csv.write_text(
        "Date,Time,Ele,RQly\n2026-10-19,15:32:37,2,98\n"
    )
    additional_markers = tuple(
        LandmarkMarker(
            BASE + timedelta(seconds=62 + index * 6),
            BASE + timedelta(seconds=65 + index * 6),
            30,
        )
        for index in range(5)
    )
    additional = _AdditionalWalk(
        source_path=additional_csv.resolve(),
        parent_baseline_id=baseline_record.baseline_id,
        label="October 19 Walk 2",
        antenna="Horizontal receiver antenna",
        settings=baseline_record.settings,
        candidates=additional_markers,
        candidate_numbers=(1, 2, 3, 4, 5),
        landmarks=additional_markers,
        direction_used="higher",
        direction_assessment="Auto selected higher from sustained holds.",
        recording_start=BASE + timedelta(seconds=60),
        recording_end=BASE + timedelta(seconds=92),
        source_sha256=fingerprint_csv(additional_csv),
    )
    walk_record = range_store.add_additional_walk(additional)
    return (
        source,
        observation.observation_id,
        baseline_record.baseline_id,
        walk_record.walk_id,
    )


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_successful_migration_preserves_bytes_and_reconstructs_records(tmp_path):
    source, observation_id, baseline_id, walk_id = _create_source(tmp_path)
    before = _snapshot(source)
    destination = tmp_path / "app-data" / "ArduPlaneTools"

    result = migrate_persistent_data(source, destination, apply=True)

    assert result.applied is True
    assert _snapshot(source) == before
    assert _snapshot(destination) == before
    packs = BatteryPackStore(destination / "battery_packs.json")
    assert packs.pack_ids == ("Pack A",)
    assert packs.association_for(FINGERPRINT).state is LogPackState.TRACKED
    observations = BatteryPackHistoryStore(
        destination / "battery_pack_history.json"
    ).observations
    assert [item.observation_id for item in observations] == [observation_id]
    range_store = RangeWalkHistoryStore(
        destination / "range_walk_history.json",
        destination / "range_walk_csv",
    )
    records, walks = range_store.validated_history()
    assert [record.baseline_id for record in records] == [baseline_id]
    assert [walk.walk_id for walk in walks] == [walk_id]
    assert walks[0].parent_baseline_id == baseline_id
    assert fingerprint_csv(records[0].stored_csv_path) == records[0].csv_sha256
    assert fingerprint_csv(walks[0].stored_csv_path) == walks[0].csv_sha256


def test_dry_run_uses_default_destination_without_writing(tmp_path, monkeypatch):
    source, _, _, _ = _create_source(tmp_path)
    destination = tmp_path / "not-created" / "ArduPlaneTools"
    monkeypatch.setattr(
        migration_module,
        "application_data_directory",
        lambda: destination,
    )

    result = migrate_persistent_data(source)

    assert result.applied is False
    assert result.destination == destination
    assert not destination.parent.exists()


def test_existing_destination_is_never_modified(tmp_path):
    source, _, _, _ = _create_source(tmp_path)
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep")

    with pytest.raises(DataMigrationError, match="already exists"):
        migrate_persistent_data(source, destination, apply=True)

    assert sentinel.read_text() == "keep"
    assert list(destination.iterdir()) == [sentinel]


def test_destination_appearing_during_staging_is_preserved(tmp_path, monkeypatch):
    source, _, _, _ = _create_source(tmp_path)
    destination = tmp_path / "target-parent" / "ArduPlaneTools"
    real_copy = migration_module.shutil.copy2
    copy_count = 0

    def create_destination_then_copy(source_path, target_path):
        nonlocal copy_count
        copy_count += 1
        if copy_count == 1:
            destination.mkdir()
            (destination / "keep.txt").write_text("created concurrently")
        return real_copy(source_path, target_path)

    monkeypatch.setattr(
        migration_module.shutil,
        "copy2",
        create_destination_then_copy,
    )
    with pytest.raises(DataMigrationError, match="already exists"):
        migrate_persistent_data(source, destination, apply=True)

    assert (destination / "keep.txt").read_text() == "created concurrently"
    assert sorted(destination.parent.iterdir()) == [destination]


def test_corrupt_json_is_rejected_without_destination(tmp_path):
    source, _, _, _ = _create_source(tmp_path)
    (source / "battery_packs.json").write_text("{not JSON")
    destination = tmp_path / "destination"

    with pytest.raises(DataMigrationError, match="validation failed"):
        migrate_persistent_data(source, destination, apply=True)

    assert not destination.exists()


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_missing_or_changed_managed_csv_is_rejected(tmp_path, change):
    source, _, _, _ = _create_source(tmp_path)
    managed_csv = next((source / "range_walk_csv").iterdir())
    if change == "missing":
        managed_csv.unlink()
    else:
        managed_csv.write_text("changed evidence\n")

    with pytest.raises(DataMigrationError, match="validation failed"):
        migrate_persistent_data(source, tmp_path / "destination", apply=True)


def test_unreferenced_managed_csv_and_symlinks_are_rejected(tmp_path):
    source, _, _, _ = _create_source(tmp_path)
    (source / "range_walk_csv" / "unexpected.csv").write_text("unexpected")
    with pytest.raises(DataMigrationError, match="unexpected"):
        migrate_persistent_data(source, tmp_path / "first-destination")

    (source / "range_walk_csv" / "unexpected.csv").unlink()
    packs = source / "battery_packs.json"
    packs.rename(source / "packs-real.json")
    packs.symlink_to(source / "packs-real.json")
    with pytest.raises(DataMigrationError, match="symlink"):
        migrate_persistent_data(source, tmp_path / "second-destination")


def test_copy_failure_cleans_staging_and_preserves_source(tmp_path, monkeypatch):
    source, _, _, _ = _create_source(tmp_path)
    before = _snapshot(source)
    destination = tmp_path / "target-parent" / "ArduPlaneTools"

    def fail_copy(_source, _target):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(migration_module.shutil, "copy2", fail_copy)
    with pytest.raises(DataMigrationError, match="simulated copy failure"):
        migrate_persistent_data(source, destination, apply=True)

    assert _snapshot(source) == before
    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_schema_valid_staged_json_identity_change_cleans_staging(
    tmp_path, monkeypatch
):
    source, _, _, _ = _create_source(tmp_path)
    destination = tmp_path / "target-parent" / "ArduPlaneTools"
    real_copy = migration_module.shutil.copy2

    def corrupt_copy(source_path, target_path):
        result = real_copy(source_path, target_path)
        if Path(source_path).name == "battery_packs.json":
            with Path(target_path).open("a", encoding="utf-8") as copied_file:
                copied_file.write("\n")
        return result

    monkeypatch.setattr(migration_module.shutil, "copy2", corrupt_copy)
    with pytest.raises(DataMigrationError, match="identity differs"):
        migrate_persistent_data(source, destination, apply=True)

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_cli_requires_explicit_mode_and_reports_dry_run(tmp_path, capsys):
    source, _, _, _ = _create_source(tmp_path)
    destination = tmp_path / "destination"

    assert main([str(source), "--destination", str(destination), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "Validated dry run" in output
    assert "battery_packs.json" in output
    assert not destination.exists()


def test_no_supported_data_is_rejected(tmp_path):
    source = tmp_path / "Data"
    source.mkdir()
    (source / "unrelated.txt").write_text("leave behind")

    with pytest.raises(DataMigrationError, match="no supported"):
        migrate_persistent_data(source, tmp_path / "destination")
