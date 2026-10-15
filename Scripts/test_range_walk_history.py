"""Portable persistence tests for Range-Walk Walk 1 baselines."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import core.range_walk_history as history_module
from core.range_walk import LandmarkMarker, WalkSettings
from core.range_walk_history import (
    DuplicateRangeWalkEvidenceError,
    RangeWalkHistoryError,
    RangeWalkHistoryFormatError,
    RangeWalkHistoryStore,
    fingerprint_csv,
)
from gui.range_walk_adapter import RangeWalkPreviewResult, create_walk1_baseline


BASE = datetime(2026, 10, 12, 13, 37, 20)


def _baseline(tmp_path, name="walk.csv", content="csv evidence\n", offset=0):
    source = tmp_path / name
    source.write_text(content)
    markers = tuple(
        LandmarkMarker(
            BASE + timedelta(seconds=offset + 2 + index * 6),
            BASE + timedelta(seconds=offset + 5.6 + index * 6),
            37,
        )
        for index in range(5)
    )
    preview = RangeWalkPreviewResult(
        source.resolve(),
        1,
        BASE,
        BASE + timedelta(seconds=offset + 34),
        340,
        markers,
        "higher",
        "higher",
        True,
        "Auto selected higher from complete sustained holds.",
        "preview",
    )
    return create_walk1_baseline(
        preview,
        (1, 2, 3, 4, 5),
        ("Gate", "Tree", "Fence", "Shed", "Far turnaround"),
        "Original receiver antenna",
        "Walk 1 baseline",
        WalkSettings("100 mW", "250 Hz", "2.4 GHz", "Off"),
    )


def _store(tmp_path):
    return RangeWalkHistoryStore(
        tmp_path / "Data" / "range_walk_history.json",
        tmp_path / "Data" / "range_walk_csv",
    )


def test_round_trip_preserves_identity_markers_and_managed_csv(tmp_path):
    baseline = _baseline(tmp_path)
    store = _store(tmp_path)

    saved = store.add_baseline(baseline)
    reloaded = _store(tmp_path).validated_records()[0]

    assert reloaded.baseline_id == saved.baseline_id
    assert len(reloaded.baseline_id) == 32
    assert reloaded.csv_sha256 == fingerprint_csv(baseline.source_path)
    assert reloaded.stored_csv_path.read_text() == "csv evidence\n"
    assert reloaded.candidates == baseline.candidates
    assert reloaded.landmarks == baseline.landmarks
    assert reloaded.candidate_numbers == (1, 2, 3, 4, 5)
    assert reloaded.turnaround == "Far turnaround"
    assert reloaded.direction_assessment == baseline.direction_assessment
    raw = json.loads(store.path.read_text())
    persisted = raw["baselines"][saved.baseline_id]
    assert persisted["record_type"] == "walk1_baseline"
    assert persisted["evidence_semantics_version"] == (
        "range-walk-gui-auto-33pct-neutral-v1"
    )


def test_managed_csv_survives_original_deletion(tmp_path):
    baseline = _baseline(tmp_path)
    record = _store(tmp_path).add_baseline(baseline)

    baseline.source_path.unlink()

    assert _store(tmp_path).validated_records()[0].stored_csv_path == (
        record.stored_csv_path
    )
    assert record.stored_csv_path.is_file()


def test_duplicate_csv_is_rejected_without_second_copy_or_record(tmp_path):
    store = _store(tmp_path)
    first = _baseline(tmp_path)
    store.add_baseline(first)
    duplicate = _baseline(tmp_path, name="renamed.csv", content="csv evidence\n")

    with pytest.raises(DuplicateRangeWalkEvidenceError, match="already saved"):
        store.add_baseline(duplicate)

    assert len(store.records) == 1
    assert len(list(store.evidence_dir.glob("*.csv"))) == 1


def test_multiple_distinct_baselines_do_not_overwrite_records(tmp_path):
    store = _store(tmp_path)
    first = store.add_baseline(_baseline(tmp_path, content="first\n"))
    second = store.add_baseline(
        _baseline(tmp_path, name="second.csv", content="second\n", offset=60)
    )

    records = _store(tmp_path).validated_records()
    assert {record.baseline_id for record in records} == {
        first.baseline_id,
        second.baseline_id,
    }
    assert len(list(store.evidence_dir.glob("*.csv"))) == 2


def test_failed_history_write_leaves_no_partial_record_or_csv(tmp_path, monkeypatch):
    store = _store(tmp_path)
    baseline = _baseline(tmp_path)

    def fail(_records):
        raise OSError("simulated write failure")

    monkeypatch.setattr(store, "_save", fail)
    with pytest.raises(OSError, match="simulated write failure"):
        store.add_baseline(baseline)

    assert store.records == ()
    assert not store.path.exists()
    assert list(store.evidence_dir.iterdir()) == []


def test_atomic_replace_failure_preserves_existing_history(tmp_path, monkeypatch):
    store = _store(tmp_path)
    first = store.add_baseline(_baseline(tmp_path, content="first\n"))
    original_history = store.path.read_bytes()
    original_replace = history_module.os.replace

    def replace(source, destination):
        if Path(destination) == store.path:
            raise OSError("simulated atomic replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr(history_module.os, "replace", replace)
    with pytest.raises(OSError, match="atomic replace failure"):
        store.add_baseline(
            _baseline(tmp_path, name="second.csv", content="second\n", offset=60)
        )

    assert store.path.read_bytes() == original_history
    assert store.records == (first,)
    assert len(list(store.evidence_dir.glob("*.csv"))) == 1


def test_conflicting_checksum_named_managed_file_is_not_overwritten(tmp_path):
    baseline = _baseline(tmp_path)
    store = _store(tmp_path)
    store.evidence_dir.mkdir(parents=True)
    target = store.evidence_dir / f"{fingerprint_csv(baseline.source_path)}.csv"
    target.write_text("conflicting managed bytes")

    with pytest.raises(RangeWalkHistoryError, match="conflicts"):
        store.add_baseline(baseline)

    assert target.read_text() == "conflicting managed bytes"
    assert not store.path.exists()


@pytest.mark.parametrize(
    "content",
    (
        "not JSON",
        json.dumps({"version": 99, "baselines": {}}),
        json.dumps({"version": 1, "unexpected": {}}),
    ),
)
def test_corrupt_or_unsupported_history_is_rejected(tmp_path, content):
    store_path = tmp_path / "history.json"
    store_path.write_text(content)

    with pytest.raises(RangeWalkHistoryFormatError):
        RangeWalkHistoryStore(store_path, tmp_path / "csv")


@pytest.mark.parametrize("change", ("missing", "modified"))
def test_missing_or_modified_managed_csv_is_rejected(tmp_path, change):
    record = _store(tmp_path).add_baseline(_baseline(tmp_path))
    if change == "missing":
        record.stored_csv_path.unlink()
    else:
        record.stored_csv_path.write_text("modified")

    with pytest.raises(RangeWalkHistoryError, match="missing|checksum mismatch"):
        _store(tmp_path).validated_records()


def test_saved_candidate_mapping_is_strictly_validated(tmp_path):
    store = _store(tmp_path)
    store.add_baseline(_baseline(tmp_path))
    data = json.loads(store.path.read_text())
    record = next(iter(data["baselines"].values()))
    record["confirmed_markers"][0] = record["confirmed_markers"][1]
    store.path.write_text(json.dumps(data))

    with pytest.raises(
        RangeWalkHistoryFormatError,
        match="confirmed_markers|Confirmed markers",
    ):
        _store(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("baseline_schema_version", 99, "baseline schema"),
        ("evidence_semantics_version", "future-v2", "evidence semantics"),
        ("record_type", "comparison_walk", "record type"),
    ),
)
def test_unsupported_record_versions_and_types_are_rejected(
    tmp_path, field, value, message
):
    store = _store(tmp_path)
    store.add_baseline(_baseline(tmp_path))
    data = json.loads(store.path.read_text())
    next(iter(data["baselines"].values()))[field] = value
    store.path.write_text(json.dumps(data))

    with pytest.raises(RangeWalkHistoryFormatError, match=message):
        _store(tmp_path)
