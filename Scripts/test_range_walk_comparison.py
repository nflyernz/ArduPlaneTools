"""Portable tests for comparisons reconstructed from persisted Range-Walk evidence."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from core.range_walk import (
    MarkerCalibration,
    WalkSettings,
    detect_markers,
    select_landmarks,
)
from core.range_walk_history import RangeWalkHistoryError, RangeWalkHistoryStore, fingerprint_csv
from analyses.range_walk_persisted import (
    RangeWalkComparisonRequest,
    RangeWalkComparisonService,
)
from test_range_walk import LANDMARKS, _session


@dataclass(frozen=True)
class _Baseline:
    source_path: Path
    label: str
    antenna: str
    landmark_names: tuple[str, ...]
    turnaround: str
    settings: WalkSettings
    candidates: tuple
    candidate_numbers: tuple[int, ...]
    landmarks: tuple
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime
    source_sha256: str


@dataclass(frozen=True)
class _Additional:
    source_path: Path
    parent_baseline_id: str
    label: str
    antenna: str
    settings: WalkSettings
    candidates: tuple
    candidate_numbers: tuple[int | None, ...]
    landmarks: tuple
    direction_used: str
    direction_assessment: str
    recording_start: datetime
    recording_end: datetime
    source_sha256: str


def _services(tmp_path):
    history_path = tmp_path / "Data" / "range_walk_history.json"
    evidence_dir = tmp_path / "Data" / "range_walk_csv"
    return (
        RangeWalkHistoryStore(history_path, evidence_dir),
        RangeWalkComparisonService(
            history_path=history_path,
            evidence_dir=evidence_dir,
        ),
    )


def _save_baseline(tmp_path, store, *, settings=None, unavailable=()):
    session = _session(
        tmp_path, name="baseline.csv", rssi=-92, unavailable=unavailable
    )
    markers = detect_markers(session, MarkerCalibration(1024, 0))
    baseline = _Baseline(
        session.path,
        "Original antenna",
        "Original receiver and antenna orientation",
        LANDMARKS,
        LANDMARKS[-1],
        settings if settings is not None else WalkSettings("50 mW", "250 Hz", "2.4 GHz", "off"),
        markers,
        (1, 2, 3, 4, 5),
        markers,
        "higher",
        "complete holds",
        session.rows[0].clock,
        session.rows[-1].clock,
        fingerprint_csv(session.path),
    )
    return store.add_baseline(baseline)


def _save_walk(
    tmp_path,
    store,
    parent,
    *,
    name="walk2.csv",
    rssi=-82,
    unavailable=(),
    numbers=(1, 2, 3, 4, 5),
):
    session = _session(tmp_path, name=name, rssi=rssi, unavailable=unavailable)
    candidates = detect_markers(session, MarkerCalibration(1024, 0))
    walk = _Additional(
        session.path,
        parent.baseline_id,
        name.removesuffix(".csv"),
        "Comparison radio configuration",
        parent.settings,
        candidates,
        numbers,
        select_landmarks(candidates, numbers),
        "higher",
        "complete holds",
        session.rows[0].clock,
        session.rows[-1].clock,
        fingerprint_csv(session.path),
    )
    return store.add_additional_walk(walk)


def _compare(service, tmp_path, parent, *walks):
    return service.compare(
        RangeWalkComparisonRequest(
            parent.baseline_id,
            tuple(walk.walk_id for walk in walks),
            tmp_path / "graphs",
            7,
        )
    )


def test_reconstructs_exact_stored_boundaries_and_multiple_children(tmp_path):
    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    second = _save_walk(tmp_path, store, parent)
    third = _save_walk(tmp_path, store, parent, name="walk3.csv", rssi=-105)

    result = _compare(service, tmp_path, parent, second, third)

    assert [item.evidence.landmarks for item in result.walks] == [
        parent.landmarks,
        second.landmarks,
        third.landmarks,
    ]
    assert result.walks[1].evidence.sections[0].start == second.landmarks[0].release
    assert result.walks[1].evidence.sections[0].end == second.landmarks[1].onset
    assert result.walks[1].evidence.sections[0].p10_values["1RSS(dB)"] == -82
    assert result.walks[2].evidence.sections[0].p10_values["1RSS(dB)"] == -105
    assert len(result.graph_paths) == 4
    assert all(path.is_file() and path.stat().st_size > 1000 for path in result.graph_paths)


def test_missing_landmark_three_preserves_only_sections_one_and_four(tmp_path):
    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    child = _save_walk(
        tmp_path, store, parent, numbers=(1, 2, None, 4, 5)
    )

    evidence = _compare(service, tmp_path, parent, child).walks[1].evidence

    assert [section is not None for section in evidence.sections] == [
        True, False, False, True
    ]


def test_valid_section_with_all_unavailable_rf_is_not_zero_signal(tmp_path):
    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    child = _save_walk(
        tmp_path, store, parent, unavailable=((4, 8),)
    )

    result = _compare(service, tmp_path, parent, child)
    section = result.walks[1].evidence.sections[0]

    assert section is not None
    assert section.row_count > 0
    assert section.usable_counts["1RSS(dB)"] == 0
    assert section.p10_values["1RSS(dB)"] is None
    assert "1→2 | Walk 2 | Unavailable" in result.report
    assert " | 0.0 dBm" not in result.report


def test_unknown_settings_keep_measurements_with_warning(tmp_path):
    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store, settings=WalkSettings())
    child = _save_walk(tmp_path, store, parent)

    result = _compare(service, tmp_path, parent, child)

    assert result.walks[1].evidence.sections[0].p10_values["1RSS(dB)"] == -82
    assert not result.walks[1].like_for_like
    assert result.walks[1].warning == "Like-for-like RF settings not established."


def test_existing_settings_comparability_is_reused(tmp_path):
    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    child = _save_walk(tmp_path, store, parent)

    result = _compare(service, tmp_path, parent, child)

    assert result.walks[1].like_for_like
    assert not result.walks[1].warning


def test_child_cannot_be_compared_against_different_parent(tmp_path):
    store, service = _services(tmp_path)
    first = _save_baseline(tmp_path, store)
    child = _save_walk(tmp_path, store, first)
    other_session = _session(tmp_path, name="other-baseline.csv", rssi=-70)
    markers = detect_markers(other_session, MarkerCalibration(1024, 0))
    other = store.add_baseline(
        _Baseline(
            other_session.path, "Other", "Other configuration", LANDMARKS,
            LANDMARKS[-1], first.settings, markers, (1, 2, 3, 4, 5), markers,
            "higher", "complete holds", other_session.rows[0].clock,
            other_session.rows[-1].clock, fingerprint_csv(other_session.path)
        )
    )

    with pytest.raises(RangeWalkHistoryError, match="not associated"):
        _compare(service, tmp_path, other, child)


@pytest.mark.parametrize("damage", ("missing", "modified"))
def test_graph_titles_use_radio_configuration_without_changing_evidence(
    monkeypatch, tmp_path
):
    import analyses.range_walk_persisted as persisted

    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    child = _save_walk(tmp_path, store, parent)
    original = persisted.write_range_walk_graphs
    graph_labels = []

    def capture_graph_labels(walks, landmarks, output):
        graph_labels.extend(walk.label for walk in walks)
        return original(walks, landmarks, output)

    monkeypatch.setattr(persisted, "write_range_walk_graphs", capture_graph_labels)
    result = _compare(service, tmp_path, parent, child)

    assert graph_labels == [parent.antenna, child.antenna]
    assert result.walks[0].evidence.label == parent.label
    assert result.walks[1].evidence.label == child.label
    assert len(result.graph_paths) == 3


def test_missing_or_modified_managed_evidence_blocks_comparison(tmp_path, damage):
    store, service = _services(tmp_path)
    parent = _save_baseline(tmp_path, store)
    child = _save_walk(tmp_path, store, parent)
    if damage == "missing":
        child.stored_csv_path.unlink()
    else:
        child.stored_csv_path.write_text("modified")

    with pytest.raises(RangeWalkHistoryError, match="missing|checksum mismatch"):
        _compare(service, tmp_path, parent, child)
