"""Read-only mixed Battery Pack Performance presentation regressions."""

from dataclasses import replace

import pytest
from analyses.battery import (
    BatteryPackPerformancePresentation,
    format_pack_performance_report,
)
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_history_protection import journal_path
from core.battery_pack_history_v2 import (
    BatteryPackHistoryV2Store,
    physical_event_id_for,
    v2_observation_id_for,
)
from core.battery_pack_store import BatteryPackStore
from test_battery_pack_history import _observation as v1_observation
from test_battery_pack_history_v2 import _observation as v2_observation


def _stores(tmp_path):
    pack = BatteryPackStore(tmp_path / "packs.json")
    pack.create_and_associate("a" * 64, "Pack A")
    return pack, BatteryPackHistoryStore(tmp_path / "v1.json"), BatteryPackHistoryV2Store(tmp_path / "v2.json")


def _without_recovery(row):
    return replace(row, load=replace(
        row.load, recovery_status="unavailable", recovery_time_us=None,
        recovery_voltage_v=None, recovery_current_a=None,
        limitations=(*row.load.limitations, "No independently qualified low-load recovery."),
    ))


def _service(tmp_path):
    import sys
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    name = "stage2b3_pack_performance_adapter"
    spec = spec_from_file_location(name, Path(__file__).parent / "gui" / "pack_performance_adapter.py")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.BatteryPackPerformanceService(
        pack_store_path=tmp_path / "packs.json",
        history_store_path=tmp_path / "v1.json",
        v2_history_store_path=tmp_path / "v2.json",
    )


def test_v1_only_output_is_identical_and_missing_v2_is_not_created(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    v1.add_observations([v1_observation(source_sha256="a" * 64)])
    baseline = format_pack_performance_report(pack, v1, "Pack A")
    assert format_pack_performance_report(pack, v1, "Pack A", v2) == baseline
    assert _service(tmp_path).report("Pack A").text == baseline
    assert "FIRST TAKEOFF BY BATTERY SESSION" in baseline
    assert "ALL AUTO TAKEOFFS" in baseline
    assert not v2.path.exists()


def test_v2_only_modes_quality_and_distinct_voltage_values(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    rows = [_without_recovery(v2_observation(mode="AUTO", strict=True, source="a" * 64)),
            _without_recovery(v2_observation(mode="MANUAL", source="b" * 64)),
            _without_recovery(v2_observation(mode="FBWA", source="c" * 64))]
    for source in ("b" * 64, "c" * 64):
        pack.associate(source, "Pack A")
    unavailable = replace(rows[2], load=replace(
        rows[2].load, onset_status="partial", t0_us=None,
        reference_status="unavailable", reference_current_a=None,
        threshold_current_a=None, t1_status="unavailable", t1_us=None,
        recovery_status="unavailable", recovery_time_us=None,
        recovery_voltage_v=None, recovery_current_a=None,
        limitations=("BAT timestamps incomplete.",)),
        plateau=replace(rows[2].plateau, status="unavailable",
                        pre_start_us=None, pre_end_us=None, pre_voltage_v=None,
                        pre_current_a=None, loaded_start_us=None, loaded_end_us=None,
                        loaded_voltage_v=None, loaded_current_a=None,
                        observed_voltage_change_v=None, current_change_a=None,
                        limitation="No qualifying load interval."))
    # A partial onset can retain raw extrema but cannot retain qualified T0 evidence.
    v2.add_observations([rows[0], rows[1], unavailable])
    text = _service(tmp_path).report("Pack A").text
    assert "EXISTING AUTO TAKEOFF HISTORY" in text
    assert "No stored AUTO takeoff observations" in text
    assert text.count("Takeoff observation") == 3
    assert "Takeoff: AUTO" in text and "Takeoff: MANUAL" in text and "Takeoff: FBWA" in text
    assert "Qualified low-current voltage drop: Qualified | 2.00 V" in text
    assert "Observed voltage difference: 1.50 V" in text
    assert "Raw observed peak current: 25.00 A" in text
    assert "BAT onset T0: Partial | Unavailable" in text
    assert "Reason: No qualifying load interval." in text
    assert "Low-load recovery: Unavailable" in text
    assert "Date/time (GPS UTC): Unavailable" in text
    assert "internal resistance" in text
    assert not v1.path.exists()


def test_mixed_overlap_ownership_reassignment_and_no_persistent_writes(tmp_path):
    pack, v1, v2 = _stores(tmp_path)
    pack.create_and_associate("b" * 64, "Other")
    v1.add_observations([v1_observation(source_sha256="a" * 64)])
    v2.add_observations([v2_observation(mode="AUTO", source="a" * 64),
                         v2_observation(mode="MANUAL", source="b" * 64, pack="Other")])
    pack.associate("a" * 64, "Other")
    before = tuple(path.read_bytes() for path in (pack.path, v1.path, v2.path))
    report = _service(tmp_path).report("Pack A").text
    assert "ALL AUTO TAKEOFFS" in report
    assert report.count("Takeoff observation") == 1
    assert "Takeoff: AUTO" in report and "Takeoff: MANUAL" not in report
    assert "are not added as physical takeoffs" in report
    assert tuple(path.read_bytes() for path in (pack.path, v1.path, v2.path)) == before
    pack.rename_pack("Pack A", "Renamed")
    assert "Takeoff: AUTO" in _service(tmp_path).report("Renamed").text


def test_v2_sorting_uses_flight_and_instance_after_source(tmp_path):
    pack, _, v2 = _stores(tmp_path)
    first = _without_recovery(v2_observation(source="a" * 64))
    delta = 20_000_000
    identity = physical_event_id_for(
        source_sha256=first.source_sha256, battery_instance=1,
        flight_start_us=first.flight_start_us + delta,
        flight_end_us=first.flight_end_us + delta,
        logged_takeoff_us=first.logged_takeoff_us + delta,
    )
    later = replace(first, physical_event_id=identity,
                    observation_id=v2_observation_id_for(identity),
                    battery_instance=1, flight_number=2,
                    flight_start_us=first.flight_start_us + delta,
                    flight_end_us=first.flight_end_us + delta,
                    logged_takeoff_us=first.logged_takeoff_us + delta,
                    load=replace(first.load, t0_us=first.load.t0_us + delta,
                                 t1_us=first.load.t1_us + delta),
                    plateau=replace(first.plateau,
                                    pre_start_us=first.plateau.pre_start_us + delta,
                                    pre_end_us=first.plateau.pre_end_us + delta,
                                    loaded_start_us=first.plateau.loaded_start_us + delta,
                                    loaded_end_us=first.plateau.loaded_end_us + delta))
    v2.add_observations([later, first])
    report = format_pack_performance_report(pack, BatteryPackHistoryStore(tmp_path / "v1.json"),
                                             "Pack A", v2)
    assert report.index("Flight: 1 | BAT instance: 0") < report.index(
        "Flight: 2 | BAT instance: 1")


@pytest.mark.parametrize("bad", ["v1", "v2"])
def test_malformed_or_unsupported_history_fails_closed(tmp_path, bad):
    pack, _, _ = _stores(tmp_path)
    path = tmp_path / f"{bad}.json"
    path.write_text('{"version": 99, "observations": {}}')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        _service(tmp_path).report("Pack A")
    assert path.read_bytes() == before
    assert pack.path.exists()


def test_pending_deletion_recovery_is_not_started_by_reporting(tmp_path):
    pack, _, _ = _stores(tmp_path)
    journal_path(pack.path).mkdir()
    before = pack.path.read_bytes()
    with pytest.raises(ValueError, match="Pending Pack deletion recovery"):
        _service(tmp_path).report("Pack A")
    assert pack.path.read_bytes() == before
    assert journal_path(pack.path).exists()


def test_cli_and_service_use_same_formatter_without_original_bin(tmp_path, monkeypatch, capsys):
    pack, v1, v2 = _stores(tmp_path)
    v2.add_observations([v2_observation(source="a" * 64)])
    expected = _service(tmp_path).report("Pack A").text
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    BatteryPackPerformancePresentation(pack, v1, v2).run()
    assert capsys.readouterr().out.split("PACK PERFORMANCE REPORT", 1)[1].strip() == (
        expected.split("PACK PERFORMANCE REPORT", 1)[1].strip()
    )
