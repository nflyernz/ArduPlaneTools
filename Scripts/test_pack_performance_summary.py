"""Synthetic four-line Pack Performance summary regressions."""

from dataclasses import replace

from analyses.battery import format_pack_performance_summary
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_history_v2 import BatteryPackHistoryV2Store
from core.battery_pack_store import BatteryPackStore
from test_battery_pack_history import _observation as v1_observation
from test_battery_pack_history_v2 import _observation as v2_observation
from test_battery_pack_history_v2_presentation import _service


def _stores(tmp_path):
    pack = BatteryPackStore(tmp_path / "packs.json")
    pack.create_and_associate("a" * 64, "Pack A")
    return pack, BatteryPackHistoryStore(tmp_path / "v1.json"), BatteryPackHistoryV2Store(tmp_path / "v2.json")


def test_missing_history_summary_has_four_explicit_lines(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    text = format_pack_performance_summary(pack, v1, v2, "Pack A")
    lines = text.splitlines()
    assert len(lines) == 4
    assert "0 source BINs" in lines[0]
    assert "Peak / min loaded: unavailable" in lines[1]
    assert "Qualified sustained-load ΔV: unavailable" in lines[2]
    assert "unavailable" in lines[3]
    assert not v1.path.exists() and not v2.path.exists()


def test_pc1_style_two_takeoffs_show_compact_individual_measurements(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    pack.associate("b" * 64, "Pack A")
    manual = v2_observation(mode="MANUAL", source="a" * 64)
    fbwa = v2_observation(mode="FBWA", source="b" * 64)
    partial = replace(fbwa, load=replace(
        fbwa.load, onset_status="partial", t0_us=None,
        reference_status="unavailable", reference_current_a=None,
        threshold_current_a=None, t1_status="unavailable", t1_us=None,
        recovery_status="unavailable", recovery_time_us=None,
        recovery_voltage_v=None, recovery_current_a=None,
        limitations=("Missing BAT onset.",)),
        plateau=replace(fbwa.plateau, status="unavailable",
                        pre_start_us=None, pre_end_us=None, pre_voltage_v=None,
                        pre_current_a=None, loaded_start_us=None, loaded_end_us=None,
                        loaded_voltage_v=None, loaded_current_a=None,
                        observed_voltage_change_v=None, current_change_a=None,
                        limitation="No qualified plateau."))
    v2.add_observations([manual, partial])
    text = format_pack_performance_summary(pack, v1, v2, "Pack A")
    lines = text.splitlines()
    assert len(lines) == 4
    assert "MANUAL 1, FBWA 1" in lines[0]
    assert "MAN F1 25.00 A / 14.00 V" in lines[1]
    assert "FBW F1 25.00 A / 14.00 V" in lines[1]
    assert "FBW F1 1.50 V" not in lines[2]
    assert "1.50 V" in lines[2]
    assert "T0 1/1/0" in lines[3]
    assert "plateau 1/0/1" in lines[3]
    assert max(map(len, lines)) <= 120


def test_mixed_auto_overlap_is_not_counted_twice(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    v1.add_observations([v1_observation(source_sha256="a" * 64)])
    v2.add_observations([v2_observation(mode="AUTO", source="a" * 64)])
    before = pack.path.read_bytes(), v1.path.read_bytes(), v2.path.read_bytes()
    lines = format_pack_performance_summary(pack, v1, v2, "Pack A").splitlines()
    assert len(lines) == 4
    assert "1 source BIN" in lines[0]
    assert "AUTO 1 | existing AUTO 1 (separate)" in lines[0]
    assert "existing AUTO:" in lines[1]
    assert max(map(len, lines)) <= 120
    assert (pack.path.read_bytes(), v1.path.read_bytes(), v2.path.read_bytes()) == before


def test_existing_auto_only_summary_keeps_its_measurements_separate(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    v1.add_observations([v1_observation(source_sha256="a" * 64)])
    lines = format_pack_performance_summary(pack, v1, v2, "Pack A").splitlines()
    assert len(lines) == 4
    assert "AUTO 0 | existing AUTO 1 (separate)" in lines[0]
    assert "existing AUTO: 20.00 A / 14.50 V" in lines[1]
    assert "Qualified sustained-load ΔV: unavailable" in lines[2]
    assert max(map(len, lines)) <= 120


def test_many_observations_use_labelled_extrema_with_provenance(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    rows = []
    for index, source in enumerate("abcd"):
        fingerprint = source * 64
        if index:
            pack.associate(fingerprint, "Pack A")
        row = v2_observation(mode="MANUAL" if index % 2 else "FBWA",
                             source=fingerprint)
        rows.append(replace(row, load=replace(
            row.load, peak_current_a=20.0 + index,
            minimum_loaded_voltage_v=14.0 - index * 0.1)))
    v2.add_observations(rows)
    lines = format_pack_performance_summary(pack, v1, v2, "Pack A").splitlines()
    assert len(lines) == 4
    assert "20.00–23.00 A" in lines[1]
    assert "13.70–14.00 V" in lines[1]
    assert "(4 records)" in lines[1]
    assert "Qualified sustained-load ΔV (4):" in lines[2]
    assert max(map(len, lines)) <= 120


def test_refresh_carries_distinct_read_only_summaries_for_each_pack(tmp_path):
    pack, _, v2 = _stores(tmp_path)
    pack.create_and_associate("b" * 64, "Pack B")
    v2.add_observations([v2_observation(source="a" * 64, pack="Pack A"),
                         v2_observation(source="b" * 64, pack="Pack B", mode="MANUAL")])
    before = pack.path.read_bytes(), v2.path.read_bytes()
    index = _service(tmp_path).refresh()
    summaries = dict(index.summaries)
    assert "FBWA 1" in summaries["Pack A"]
    assert "MANUAL 1" in summaries["Pack B"]
    assert summaries["Pack A"] != summaries["Pack B"]
    assert (pack.path.read_bytes(), v2.path.read_bytes()) == before
