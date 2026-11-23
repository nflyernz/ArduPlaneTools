"""Synthetic explicit v2 recorder and provenance regressions."""

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest
from core.battery import BatteryLoadEventType, TakeoffType
from core.battery_load_response import BatteryLoadResponse, evaluate_load_response
from core.battery_pack_history import BatteryPackHistoryError, BatteryPackHistoryStore
from core.battery_pack_history_recorder import BatteryPackHistoryRecorder
from core.battery_pack_history_v2 import (
    BatteryPackHistoryFormatError,
    BatteryPackHistoryV2Store,
)
from core.battery_pack_history_v2_recorder import (
    BatteryPackHistoryV2Recorder,
    _load_evidence,
)
from core.battery_pack_store import BatteryPackStore, fingerprint_log
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.pilot_battery_onset import observe_gps_anchored_bat
from core.pilot_plateau_voltage import ObservedPlateauVoltageComparison
from test_pilot_takeoff import _log as pilot_log


def _response(t0=4_900_000, strict=False):
    return BatteryLoadResponse(
        t0, t0 + 4_100_000, 20.0, 16.0, 25.0,
        16.0 if strict else None, 2.0 if strict else None,
        14.0, 22.0, 2.0 if strict else None,
        t0 + 9_100_000, 15.0, 4.0, t0 + 4_100_000,
        "Confirmed 80% current reduction; low-current baseline unavailable.",
    )


def _plateau(offset=0):
    return ObservedPlateauVoltageComparison(
        "Qualified observed plateaus.", offset + 3_700_000, offset + 4_700_000, 16.0, 5.0,
        offset + 5_300_000, offset + 6_300_000, 14.5, 21.0, 1.5, 16.0,
    )


def _analysis(window, instance, mode, *, strict=False):
    response = _response(window.start_us + 900_000, strict=strict)
    if mode == "AUTO":
        event = SimpleNamespace(
            event_type=BatteryLoadEventType.TAKEOFF,
            takeoff_type=TakeoffType.AUTO, instance=instance,
            flight_number=1,
        )
        return SimpleNamespace(bounded_load_events=[event],
                               battery_load_response=response,
                               pilot_controlled_takeoffs=[])
    pilot = SimpleNamespace(
        event=SimpleNamespace(flight_start_us=window.start_us,
                              mode_name=mode, time_us=window.start_us + 1_000_000),
        response=response, plateau_comparison=_plateau(window.start_us - 4_000_000),
        gps_observation=None,
    )
    return SimpleNamespace(bounded_load_events=[], battery_load_response=None,
                           pilot_controlled_takeoffs=[pilot])


def _recorder(monkeypatch, modes, analysis_factory=_analysis):
    import core.battery_pack_history_v2_recorder as module

    class Processor:
        def __init__(self, _log, window, instance, config=None):
            self.window = window
            self.instance = instance

        def available_instances(self):
            return tuple(range(len(modes)))

        def analyse(self):
            mode = modes[self.instance]
            return None if mode is None else analysis_factory(self.window, self.instance, mode)

    monkeypatch.setattr(module, "BatteryProcessor", Processor)
    return BatteryPackHistoryV2Recorder(object())


@pytest.mark.parametrize("mode,classification", [
    ("AUTO", "AUTO"), ("MANUAL", "PILOT_CONTROLLED"),
    ("FBWA", "PILOT_CONTROLLED"),
])
def test_recorder_writes_one_valid_mode_specific_observation(tmp_path, monkeypatch,
                                                              mode, classification):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"synthetic BIN identity")
    window = FlightWindow(4_000_000, 20_000_000)
    log = FlightLog(messages={"GPS": pd.DataFrame({"TimeUS": [window.start_us]})},
                    flights=[window])
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    assert _recorder(monkeypatch, (mode,)).record(
        log, source, fingerprint_log(source), "Pack A", store,
    ) == 1
    row = store.observations[0]
    assert (row.takeoff_type, row.flight_mode) == (classification, mode)
    assert row.logged_takeoff_us == (window.start_us if mode == "AUTO" else 5_000_000)
    assert row.load.onset_status == "qualified"
    assert row.load.voltage_drop_status == "partial"
    assert row.load.qualified_voltage_drop_v is None
    assert row.plateau.status == ("unavailable" if mode == "AUTO" else "qualified")
    assert row.recorded_at_utc is None


def test_multiple_flights_instances_replay_and_first_ingest_provenance(tmp_path, monkeypatch):
    source = tmp_path / "first.bin"
    source.write_bytes(b"same content")
    windows = [FlightWindow(4_000_000, 20_000_000),
               FlightWindow(24_000_000, 40_000_000)]
    log = FlightLog(messages={"GPS": pd.DataFrame({"TimeUS": [w.start_us for w in windows]})},
                    flights=windows)
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    recorder = _recorder(monkeypatch, ("MANUAL", "FBWA", None))
    digest = fingerprint_log(source)
    assert recorder.record(log, source, digest, "Pack A", store) == 4
    first_bytes = store.path.read_bytes()
    renamed = tmp_path / "renamed.bin"
    renamed.write_bytes(source.read_bytes())
    assert recorder.record(log, renamed, digest, "Renamed Pack", store) == 0
    assert store.path.read_bytes() == first_bytes
    assert {row.pack_id_at_ingest for row in store.observations} == {"Pack A"}
    assert {row.source_filename for row in store.observations} == {"first.bin"}


def test_auto_without_logged_window_start_is_excluded(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"AUTO")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    assert _recorder(monkeypatch, ("AUTO",)).record(
        log, source, fingerprint_log(source), "Pack A", store,
    ) == 0
    assert not store.path.exists()


def test_empty_flights_still_run_pre_write_validation(tmp_path):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"no FlightWindows")
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    calls = []
    recorder = BatteryPackHistoryV2Recorder(None)
    assert recorder.record(FlightLog(flights=[]), source, fingerprint_log(source),
                           "Pack A", store, pre_write=lambda: calls.append("validated")) == 0
    assert calls == ["validated"]
    assert not store.path.exists()
    with pytest.raises(RuntimeError, match="stale empty flight"):
        recorder.record(FlightLog(flights=[]), source, fingerprint_log(source),
                        "Pack A", store,
                        pre_write=lambda: (_ for _ in ()).throw(RuntimeError("stale empty flight")))
    assert not store.path.exists()


def test_conflicting_batch_does_not_rewrite_valid_v1_or_v2(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"batch")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    recorder = _recorder(monkeypatch, ("MANUAL",))
    digest = fingerprint_log(source)
    assert recorder.record(log, source, digest, "Pack A", store) == 1
    original = store.path.read_bytes()
    v1 = BatteryPackHistoryStore(tmp_path / "v1.json")
    pack = BatteryPackStore(tmp_path / "packs.json")
    pack.create_and_associate(digest, "Pack A")
    pack_bytes = pack.path.read_bytes()
    def changed_analysis(window, instance, mode):
        analysis = _analysis(window, instance, mode)
        pilot = analysis.pilot_controlled_takeoffs[0]
        return SimpleNamespace(
            bounded_load_events=[], battery_load_response=None,
            pilot_controlled_takeoffs=[SimpleNamespace(
                event=pilot.event,
                response=replace(pilot.response, raw_peak_current_a=99.0),
                plateau_comparison=pilot.plateau_comparison, gps_observation=None,
            )],
        )

    changed = _recorder(monkeypatch, ("MANUAL",), changed_analysis)
    with pytest.raises(BatteryPackHistoryError, match="Conflicting evidence"):
        changed.record(log, source, digest, "Pack A", store)
    assert store.path.read_bytes() == original
    assert not v1.path.exists()
    assert pack.path.read_bytes() == pack_bytes


def test_invalid_later_candidate_rejects_entire_batch(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"invalid later candidate")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")

    def analysis_with_invalid_t0(window, instance, mode):
        analysis = _analysis(window, instance, mode)
        if instance == 1:
            pilot = analysis.pilot_controlled_takeoffs[0]
            return SimpleNamespace(
                bounded_load_events=[], battery_load_response=None,
                pilot_controlled_takeoffs=[SimpleNamespace(
                    event=pilot.event,
                    response=replace(pilot.response, t0_us=9_000_001,
                                     t1_us=13_100_001, follow_up_time_us=14_000_001),
                    plateau_comparison=pilot.plateau_comparison,
                    gps_observation=None,
                )],
            )
        return analysis

    recorder = _recorder(monkeypatch, ("MANUAL", "FBWA"), analysis_with_invalid_t0)
    with pytest.raises(ValueError, match="Pilot T0 is outside takeoff search window"):
        recorder.record(log, source, fingerprint_log(source), "Pack A", store)
    assert not store.path.exists()


def test_real_pilot_analysis_results_feed_standalone_recorder(tmp_path):
    source = tmp_path / "synthetic.bin"
    source.write_bytes(b"synthetic pilot telemetry identity")
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    assert BatteryPackHistoryV2Recorder(None).record(
        pilot_log(), source, fingerprint_log(source), "Pack A", store,
    ) == 2
    assert {row.flight_mode for row in store.observations} == {"MANUAL", "FBWA"}
    assert all(row.load.onset_status == "qualified" for row in store.observations)
    assert all(row.plateau.status == "qualified" for row in store.observations)


def test_follow_up_at_fourteen_amps_is_not_qualified_recovery(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"loaded five-second follow-up")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])

    def strict_analysis(window, instance, mode):
        analysis = _analysis(window, instance, mode, strict=True)
        pilot = analysis.pilot_controlled_takeoffs[0]
        return SimpleNamespace(bounded_load_events=[], battery_load_response=None,
                               pilot_controlled_takeoffs=[SimpleNamespace(
                                   event=pilot.event,
                                   response=replace(pilot.response, follow_up_current_a=14.0),
                                   plateau_comparison=pilot.plateau_comparison,
                                   gps_observation=None)])

    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    assert _recorder(monkeypatch, ("MANUAL",), strict_analysis).record(
        log, source, fingerprint_log(source), "Pack A", store,
    ) == 1
    row = store.observations[0]
    assert (row.load.reference_current_a, row.load.threshold_current_a) == (20.0, 16.0)
    assert row.load.t1_status == "qualified"  # 14 A is below the 16 A T1 threshold.
    assert row.load.voltage_drop_status == "qualified"
    assert row.load.qualified_voltage_drop_v == 2.0
    assert row.plateau.status == "qualified"
    assert row.plateau.observed_voltage_change_v == 1.5
    assert row.load.recovery_status == "unavailable"
    assert (row.load.recovery_time_us, row.load.recovery_voltage_v,
            row.load.recovery_current_a) == (None, None, None)
    assert any("14 A" in text and "not independently qualified" in text
               for text in row.load.limitations)


def test_real_evaluator_t1_and_loaded_five_second_follow_up_are_distinct():
    rows = []
    for tick in range(181):
        stamp = tick * 100_000
        current = 2.0 if stamp < 1_000_000 else 20.0 if stamp < 5_000_000 else 14.0
        voltage = 16.0 if current == 2.0 else 14.0 if current == 20.0 else 15.0
        rows.append({"TimeUS": stamp, "Inst": 0,
                     "Volt": voltage, "Curr": current})
    response = evaluate_load_response(pd.DataFrame(rows), 0, 1_000_000, 18_000_000)
    assert response.reference_current_a == 20.0
    assert response.threshold_current_a == 16.0
    assert response.t1_us is not None
    assert response.follow_up_current_a == 14.0
    assert response.follow_up_time_us >= response.t1_us + 5_000_000
    load = _load_evidence(response)
    assert load.t1_status == "qualified"
    assert load.qualified_voltage_drop_v == 2.0
    assert load.recovery_status == "unavailable"
    assert load.recovery_time_us is None
    assert any("14 A" in text and "not independently qualified" in text
               for text in load.limitations)


@pytest.mark.parametrize("damage,warning", [
    ("complete", "GPS-anchored observed BAT samples"),
    ("gap", "have gaps"),
    ("invalid timestamp", "invalid timestamps"),
    ("missing pair", "missing voltage/current values"),
])
def test_gps_anchored_quality_is_retained_with_raw_extrema(damage, warning):
    bat = pd.DataFrame([
        {"TimeUS": 10_000_000, "Inst": 0, "Volt": 16.0, "Curr": 2.0},
        {"TimeUS": 10_100_000, "Inst": 0, "Volt": 14.0, "Curr": 20.0},
        {"TimeUS": 10_200_000, "Inst": 0, "Volt": 15.0, "Curr": 14.0},
    ])
    if damage == "gap":
        bat.loc[1:, "TimeUS"] += 500_000
    elif damage == "invalid timestamp":
        bat.loc[1, "TimeUS"] = float("nan")
    elif damage == "missing pair":
        bat.loc[1, "Curr"] = float("nan")
    observation = observe_gps_anchored_bat(bat, 0, 10_000_000, 30_000_000)
    response = replace(_response(), t0_us=None, t1_us=None,
                       reference_current_a=None, threshold_current_a=None,
                       raw_peak_current_a=None, minimum_voltage_v=None,
                       current_at_minimum_a=None, baseline_voltage_v=None,
                       baseline_current_a=None, voltage_drop_v=None,
                       follow_up_time_us=None, follow_up_voltage_v=None,
                       follow_up_current_a=None)
    load = _load_evidence(response, observation)
    assert observation.status in load.limitations
    assert warning in observation.status
    assert load.peak_current_a == observation.raw_peak_current_a
    assert load.minimum_loaded_voltage_v == observation.minimum_voltage_v
    assert load.onset_status == "partial"
    assert load.t0_us is None
    assert load.qualified_voltage_drop_v is None
    assert load.recovery_status == "unavailable"
    assert observation.status in _load_evidence(None, observation).limitations


@pytest.mark.parametrize("damage,expected_onset", [
    ("gap", "qualified"), ("invalid timestamp", "partial"),
])
def test_real_pilot_bat_damage_retains_qualified_and_partial_evidence(
        tmp_path, damage, expected_onset):
    source = tmp_path / "synthetic.bin"
    source.write_bytes(b"synthetic damaged BAT telemetry")
    log = pilot_log()
    bat = log.messages["BAT"]
    if damage == "gap":
        bat.drop(bat.index[bat["TimeUS"].between(4_000_000, 5_000_000)], inplace=True)
    else:
        bat.loc[bat["TimeUS"] == 4_500_000, "TimeUS"] = float("nan")
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    assert BatteryPackHistoryV2Recorder(None).record(
        log, source, fingerprint_log(source), "Pack A", store,
    ) == 2
    rows = {row.flight_mode: row for row in store.observations}
    assert rows["FBWA"].load.onset_status == expected_onset
    assert rows["FBWA"].plateau.status == "unavailable"
    assert rows["FBWA"].load.qualified_voltage_drop_v is None
    if damage == "invalid timestamp":
        assert any("GPS-anchored observed BAT samples" in text
                   for text in rows["FBWA"].load.limitations)
    assert rows["MANUAL"].load.onset_status == "qualified"
    assert rows["MANUAL"].plateau.status == "qualified"


def test_real_auto_analysis_uses_logged_gps_window_start(tmp_path):
    from core.params import ParameterHistory
    from test_battery_load_response import _bat

    source = tmp_path / "synthetic.bin"
    source.write_bytes(b"synthetic AUTO telemetry identity")
    window = FlightWindow(1_500_000, 25_000_000)
    log = FlightLog(
        messages={
            "BAT": _bat(),
            "GPS": pd.DataFrame({"TimeUS": [window.start_us]}),
            "MODE": pd.DataFrame([{"TimeUS": 500_000, "ModeNum": 13},
                                  {"TimeUS": 7_000_000, "ModeNum": 5}]),
            "MSG": pd.DataFrame([{"TimeUS": 900_000, "Message": "Triggered AUTO"}]),
        },
        parameter_history=ParameterHistory({}), flights=[window],
    )
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    assert BatteryPackHistoryV2Recorder(None).record(
        log, source, fingerprint_log(source), "Pack A", store,
    ) == 1
    row = store.observations[0]
    assert row.logged_takeoff_us == window.start_us
    assert row.load.t0_us == 1_000_000
    assert row.plateau.status == "unavailable"


def test_incomplete_bat_keeps_raw_values_without_qualified_measurements(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"incomplete BAT")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])

    def partial_analysis(window, instance, mode):
        pilot = _analysis(window, instance, mode).pilot_controlled_takeoffs[0]
        partial = replace(pilot.response, t0_us=None, t1_us=None,
                          reference_current_a=None, threshold_current_a=None,
                          baseline_voltage_v=None, baseline_current_a=None,
                          voltage_drop_v=None, follow_up_time_us=None,
                          follow_up_voltage_v=None, follow_up_current_a=None,
                          status="BAT sampling gap and invalid timestamp.", gaps=True)
        return SimpleNamespace(bounded_load_events=[], battery_load_response=None,
                               pilot_controlled_takeoffs=[SimpleNamespace(
                                   event=pilot.event, response=partial,
                                   plateau_comparison=None, gps_observation=None)])

    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    recorder = _recorder(monkeypatch, ("MANUAL",), partial_analysis)
    assert recorder.record(log, source, fingerprint_log(source), "Pack A", store) == 1
    load = store.observations[0].load
    assert load.onset_status == "partial"
    assert load.peak_current_a == 25.0
    assert load.minimum_loaded_voltage_v == 14.0
    assert load.voltage_drop_status == "partial"
    assert load.qualified_voltage_drop_v is None
    assert "sampling gap" in load.limitations[0]


def test_invalid_store_and_wrong_store_are_rejected_without_writes(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"identity")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])
    corrupt = tmp_path / "v2.json"
    corrupt.write_text('{"version": 99, "observations": {}}')
    before = corrupt.read_bytes()
    with pytest.raises(BatteryPackHistoryFormatError):
        BatteryPackHistoryV2Store(corrupt)
    recorder = _recorder(monkeypatch, ("MANUAL",))
    with pytest.raises(BatteryPackHistoryError, match="explicit v2 history store"):
        recorder.record(log, source, fingerprint_log(source), "Pack A",
                        BatteryPackHistoryStore(tmp_path / "v1.json"))
    assert corrupt.read_bytes() == before
    assert not (tmp_path / "v1.json").exists()


def test_corruption_after_store_creation_is_not_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "flight.bin"
    source.write_bytes(b"late corruption")
    log = FlightLog(flights=[FlightWindow(4_000_000, 20_000_000)])
    store = BatteryPackHistoryV2Store(tmp_path / "v2.json")
    store.path.write_text('{"version": 99, "observations": {}}')
    before = store.path.read_bytes()
    with pytest.raises(BatteryPackHistoryFormatError):
        _recorder(monkeypatch, ("MANUAL",)).record(
            log, source, fingerprint_log(source), "Pack A", store,
        )
    assert store.path.read_bytes() == before


def test_ordinary_v1_recording_never_invokes_v2_recorder(tmp_path, monkeypatch):
    from core.params import ParameterHistory
    from test_battery_load_response import _bat

    source = tmp_path / "flight.bin"
    source.write_bytes(b"v1 only")
    window = FlightWindow(1_500_000, 25_000_000)
    log = FlightLog(messages={
        "BAT": _bat(),
        "GPS": pd.DataFrame({"TimeUS": [window.start_us]}),
        "MODE": pd.DataFrame([{"TimeUS": 500_000, "ModeNum": 13},
                              {"TimeUS": 7_000_000, "ModeNum": 5}]),
        "MSG": pd.DataFrame([{"TimeUS": 900_000, "Message": "Triggered AUTO"}]),
    }, parameter_history=ParameterHistory({}), flights=[window])

    def forbidden(*_args, **_kwargs):
        raise AssertionError("v2 recorder invoked by ordinary v1 path")

    monkeypatch.setattr(BatteryPackHistoryV2Recorder, "record", forbidden)
    v1 = BatteryPackHistoryStore(tmp_path / "v1.json")
    assert BatteryPackHistoryRecorder(None).record(
        log, source, fingerprint_log(source), "Pack A", v1,
    ) == 1
    assert v1.path.exists()
    assert not (tmp_path / "v2.json").exists()
