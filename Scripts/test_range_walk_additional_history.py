"""Qt-independent persistence tests for additional Range-Walk records."""

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.range_walk import LandmarkMarker, WalkSettings, select_landmarks
from core.range_walk_history import (
    DuplicateRangeWalkEvidenceError,
    RangeWalkHistoryError,
    RangeWalkHistoryStore,
    fingerprint_csv,
)
from test_range_walk_history import _baseline, _store


BASE = datetime(2026, 10, 12, 14, 0, 0)


@dataclass(frozen=True)
class AdditionalWalkFixture:
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


def _walk(
    tmp_path,
    parent,
    *,
    name="walk2.csv",
    content="walk 2 evidence\n",
    numbers=(1, 2, 3, 4, 5),
    candidate_count=5,
    offset=0,
):
    source = tmp_path / name
    source.write_text(content)
    candidates = tuple(
        LandmarkMarker(
            BASE + timedelta(seconds=offset + 2 + index * 6),
            BASE + timedelta(seconds=offset + 5.6 + index * 6),
            37,
        )
        for index in range(candidate_count)
    )
    return AdditionalWalkFixture(
        source.resolve(),
        parent.baseline_id,
        f"Additional {name}",
        "Receiver relocated lower in fuselage",
        parent.settings,
        candidates,
        numbers,
        select_landmarks(candidates, numbers, baseline=False),
        "higher",
        "Auto selected higher from complete sustained holds.",
        BASE + timedelta(seconds=offset),
        BASE + timedelta(seconds=offset + 40),
        fingerprint_csv(source),
    )


def test_version1_history_loads_intact_and_upgrades_on_next_write(tmp_path):
    store = _store(tmp_path)
    baseline = store.add_baseline(_baseline(tmp_path))
    data = json.loads(store.path.read_text())
    data["version"] = 1
    data.pop("walks")
    store.path.write_text(json.dumps(data))

    legacy = _store(tmp_path)
    assert legacy.records == (baseline,)
    assert legacy.walks == ()
    saved = legacy.add_additional_walk(_walk(tmp_path, baseline))

    upgraded = json.loads(store.path.read_text())
    assert upgraded["version"] == 2
    assert set(upgraded) == {"version", "baselines", "walks"}
    assert baseline.baseline_id in upgraded["baselines"]
    assert saved.walk_id in upgraded["walks"]
    assert _store(tmp_path).records[0] == baseline


def test_multiple_walks_group_under_correct_independent_baselines(tmp_path):
    store = _store(tmp_path)
    first = store.add_baseline(_baseline(tmp_path, content="baseline one\n"))
    second = store.add_baseline(
        _baseline(
            tmp_path,
            name="baseline2.csv",
            content="baseline two\n",
            offset=60,
        )
    )
    walk_2 = store.add_additional_walk(_walk(tmp_path, first))
    walk_3 = store.add_additional_walk(
        _walk(
            tmp_path,
            first,
            name="walk3.csv",
            content="walk three\n",
            offset=60,
        )
    )
    other = store.add_additional_walk(
        _walk(
            tmp_path,
            second,
            name="other.csv",
            content="other baseline walk\n",
            offset=120,
        )
    )

    reloaded = _store(tmp_path)
    assert {record.baseline_id for record in reloaded.records} == {
        first.baseline_id,
        second.baseline_id,
    }
    assert {walk.walk_id for walk in reloaded.walks} == {
        walk_2.walk_id,
        walk_3.walk_id,
        other.walk_id,
    }
    assert [walk.parent_baseline_id for walk in reloaded.walks].count(
        first.baseline_id
    ) == 2
    assert other.parent_baseline_id == second.baseline_id


def test_missing_landmark_three_is_explicit_and_preserves_valid_sections(tmp_path):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    saved = store.add_additional_walk(
        _walk(tmp_path, parent, numbers=(1, 2, None, 3, 4), candidate_count=4)
    )

    assert saved.candidate_numbers == (1, 2, None, 3, 4)
    assert saved.landmarks[2] is None
    assert saved.confirmed_landmark_count == 4
    assert saved.complete_section_count == 2
    assert saved.landmarks[0] == saved.candidates[0]
    assert saved.landmarks[4] == saved.candidates[3]


def test_five_markers_and_extra_candidates_retain_explicit_mapping(tmp_path):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    complete = store.add_additional_walk(_walk(tmp_path, parent))
    extra = store.add_additional_walk(
        _walk(
            tmp_path,
            parent,
            name="extra.csv",
            content="extra candidates\n",
            numbers=(1, 2, 4, 6, 7),
            candidate_count=7,
            offset=60,
        )
    )

    assert complete.confirmed_landmark_count == 5
    assert complete.complete_section_count == 4
    assert extra.candidate_numbers == (1, 2, 4, 6, 7)
    assert extra.landmarks == tuple(
        extra.candidates[index - 1] for index in (1, 2, 4, 6, 7)
    )


@pytest.mark.parametrize("numbers", ((1, 2, 2, 4, 5), (1, 3, 2, 4, 5)))
def test_duplicate_and_out_of_order_mappings_are_rejected(tmp_path, numbers):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    with pytest.raises(ValueError, match="distinct, increasing"):
        _walk(tmp_path, parent, numbers=numbers)


def test_source_integrity_and_duplicate_identity_apply_across_record_types(tmp_path):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    changed = _walk(tmp_path, parent)
    changed.source_path.write_text("changed after detection\n")
    with pytest.raises(RangeWalkHistoryError, match="detect markers again"):
        store.add_additional_walk(changed)

    duplicate = _walk(
        tmp_path,
        parent,
        name="duplicate.csv",
        content=parent.stored_csv_path.read_text(),
    )
    with pytest.raises(DuplicateRangeWalkEvidenceError, match="already saved"):
        store.add_additional_walk(duplicate)
    assert store.walks == ()


@pytest.mark.parametrize("change", ("missing", "modified"))
def test_additional_walk_managed_evidence_is_validated(tmp_path, change):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    saved = store.add_additional_walk(_walk(tmp_path, parent))
    if change == "missing":
        saved.stored_csv_path.unlink()
    else:
        saved.stored_csv_path.write_text("modified")

    with pytest.raises(RangeWalkHistoryError, match="missing|checksum mismatch"):
        _store(tmp_path).validated_history()


def test_failed_additional_write_preserves_history_and_removes_new_copy(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    history_bytes = store.path.read_bytes()

    def fail(_baselines, _walks):
        raise OSError("simulated additional-walk write failure")

    monkeypatch.setattr(store, "_save", fail)
    with pytest.raises(OSError, match="additional-walk write failure"):
        store.add_additional_walk(_walk(tmp_path, parent))

    assert store.path.read_bytes() == history_bytes
    assert store.walks == ()
    assert list(store.evidence_dir.glob("*.csv")) == [parent.stored_csv_path]


def test_corrupt_parent_reference_is_rejected(tmp_path):
    store = _store(tmp_path)
    parent = store.add_baseline(_baseline(tmp_path))
    saved = store.add_additional_walk(_walk(tmp_path, parent))
    data = json.loads(store.path.read_text())
    data["walks"][saved.walk_id]["parent_baseline_id"] = "f" * 32
    store.path.write_text(json.dumps(data))

    with pytest.raises(RangeWalkHistoryError, match="Unknown parent"):
        _store(tmp_path)


def test_baseline_metadata_update_keeps_child_inherited_settings_consistent(tmp_path):
    store = _store(tmp_path)
    baseline = _baseline(tmp_path)
    parent = store.add_baseline(baseline)
    child = store.add_additional_walk(_walk(tmp_path, parent))
    corrected = replace(
        baseline,
        settings=WalkSettings("250 mW", "150 Hz", "2.4 GHz", "Off"),
    )

    updated = store.update_baseline_metadata(
        parent.baseline_id,
        parent,
        corrected,
    )
    reloaded = _store(tmp_path)

    assert updated.settings == corrected.settings
    assert reloaded.walks[0].walk_id == child.walk_id
    assert reloaded.walks[0].settings == corrected.settings
