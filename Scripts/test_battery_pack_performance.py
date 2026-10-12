"""Focused tests for Pack Performance reporting and optional integration."""

import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest

from analyses import battery
from analyses.battery import (
    BatteryAnalysisPresentation,
    BatteryPackPerformancePresentation,
)
from core.battery_pack_history import BatteryPackHistoryStore
from core.battery_pack_store import BatteryPackStore
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.gps_time import format_utc_milliseconds, gps_week_time_to_utc
from test_battery_pack_history import _observation


SUMMARY_HEADING = "FIRST TAKEOFF BY BATTERY SESSION"
ALL_HEADING = "ALL AUTO TAKEOFFS"


def _inputs(monkeypatch, *responses):
    answers = iter(responses)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))


def _stores(tmp_path):
    return (
        BatteryPackStore(tmp_path / "battery_packs.json"),
        BatteryPackHistoryStore(tmp_path / "battery_pack_history.json"),
    )


def _section_rows(output, heading):
    section = output.split(heading, maxsplit=1)[1]
    if heading == SUMMARY_HEADING:
        section = section.split(ALL_HEADING, maxsplit=1)[0]
    rows = []
    row = None
    for line in section.splitlines():
        text = line.strip()
        if ". Date: " in text and " | Flight: " in text:
            _number, details = text.split(". Date: ", maxsplit=1)
            date, flight = details.split(" | Flight: ", maxsplit=1)
            row = [date, None, flight]
        elif row is not None and text.startswith("Source: "):
            row[1] = text.removeprefix("Source: ")
        elif row is not None and text.startswith("Capacity used (mAh): "):
            row.append(text.removeprefix("Capacity used (mAh): "))
        elif row is not None and text.startswith("Current (A): "):
            average, peak = text.removeprefix("Current (A): ").split(
                " | peak ", maxsplit=1
            )
            row.extend((average.removeprefix("average "), peak))
        elif row is not None and text.startswith("Voltage (V): "):
            pre_load, minimum = text.removeprefix("Voltage (V): ").split(
                " | minimum loaded ", maxsplit=1
            )
            row.extend((pre_load.removeprefix("pre-load "), minimum))
        elif row is not None and text.startswith("Voltage response (V): "):
            sag, recovery = text.removeprefix("Voltage response (V): ").split(
                " | recovery ", maxsplit=1
            )
            row.extend((sag.removeprefix("sag "), recovery))
            rows.append(tuple(row))
            row = None
    assert all(len(row) == 10 and row[1] is not None for row in rows)
    return rows


def _event(
    source_sha256,
    source_filename,
    event_start_us,
    *,
    flight_number=1,
    battery_instance=0,
    gps_week=2000,
    capacity_used_mah=100.0,
):
    observation = _observation(
        source_sha256=source_sha256,
        source_filename=source_filename,
        battery_instance=battery_instance,
        event_start_us=event_start_us,
        event_end_us=event_start_us + 100_000,
    )
    recorded_at_utc = format_utc_milliseconds(
        gps_week_time_to_utc(gps_week, 18_000, 18)
        + timedelta(microseconds=event_start_us - 1_000_000)
    )
    return dataclasses.replace(
        observation,
        flight_number=flight_number,
        recorded_at_utc=recorded_at_utc,
        gps_anchor_week=gps_week,
        recovery_time_us=event_start_us + 200_000,
        capacity_used_mah=capacity_used_mah,
    )


def _render(monkeypatch, capsys, pack_store, history, selection="1"):
    _inputs(monkeypatch, selection)
    BatteryPackPerformancePresentation(pack_store, history).run()
    return capsys.readouterr().out


def _associate_sources(pack_store, pack_id, sources):
    for index, source in enumerate(sources):
        if index == 0 and pack_id not in pack_store.pack_ids:
            pack_store.create_and_associate(source, pack_id)
        else:
            pack_store.associate(source, pack_id)


def test_one_session_summarizes_first_of_three_takeoffs(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    source = "1" * 64
    pack_store.create_and_associate(source, "50S-P1")
    history.add_observations(
        [
            _event(source, "log_0.bin", 3_000_000, flight_number=2),
            _event(source, "log_0.bin", 2_000_000, flight_number=1),
            _event(source, "log_0.bin", 4_000_000, flight_number=3),
        ]
    )

    output = _render(monkeypatch, capsys, pack_store, history)
    summary_rows = _section_rows(output, SUMMARY_HEADING)
    full_rows = _section_rows(output, ALL_HEADING)

    assert len(summary_rows) == 1
    assert len(full_rows) == 3
    assert summary_rows[0][1:3] == ("log_0.bin", "1")
    assert [row[2] for row in full_rows] == ["1", "2", "3"]


@pytest.mark.parametrize(
    ("pack_id", "session_counts", "summary_count", "full_count"),
    [
        ("LIPO-3900-01", (4, 1, 4), 3, 9),
        ("50S-P1", (3,), 1, 3),
        ("LIPO-2600-01", (1,), 1, 1),
    ],
)
def test_temporary_history_matches_real_pack_session_counts(
    monkeypatch,
    capsys,
    tmp_path,
    pack_id,
    session_counts,
    summary_count,
    full_count,
):
    pack_store, history = _stores(tmp_path)
    observations = []
    sources = []
    for session_index, event_count in enumerate(session_counts, start=1):
        source = str(session_index) * 64
        sources.append(source)
        for event_index in range(event_count):
            observations.append(
                _event(
                    source,
                    f"log_{session_index}.bin",
                    1_500_000 + (event_index * 700_000),
                    flight_number=event_index + 1,
                )
            )
    _associate_sources(pack_store, pack_id, sources)
    history.add_observations(observations)

    output = _render(monkeypatch, capsys, pack_store, history)

    assert len(_section_rows(output, SUMMARY_HEADING)) == summary_count
    assert len(_section_rows(output, ALL_HEADING)) == full_count


def test_earliest_event_time_wins_despite_flight_and_utc_order(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    source = "1" * 64
    pack_store.create_and_associate(source, "Pack A")
    earlier_event_with_later_utc = _event(
        source,
        "session.bin",
        2_000_000,
        flight_number=9,
        gps_week=2001,
        capacity_used_mah=111.0,
    )
    later_event_with_earlier_utc = _event(
        source,
        "session.bin",
        3_000_000,
        flight_number=1,
        gps_week=1999,
        capacity_used_mah=222.0,
    )
    history.add_observations(
        [later_event_with_earlier_utc, earlier_event_with_later_utc]
    )

    output = _render(monkeypatch, capsys, pack_store, history)
    summary_rows = _section_rows(output, SUMMARY_HEADING)
    full_rows = _section_rows(output, ALL_HEADING)

    assert len(summary_rows) == 1
    assert summary_rows[0][2] == "9"
    assert summary_rows[0][3] == "111.00"
    assert [row[3] for row in full_rows] == ["222.00", "111.00"]


def test_exact_event_start_ties_resolve_deterministically():
    source = "1" * 64
    first = _event(
        source,
        "session.bin",
        2_000_000,
        battery_instance=0,
    )
    second = _event(
        source,
        "session.bin",
        2_000_000,
        battery_instance=1,
    )

    forward = BatteryPackPerformancePresentation._first_takeoffs_by_session(
        [first, second]
    )
    reverse = BatteryPackPerformancePresentation._first_takeoffs_by_session(
        [second, first]
    )

    assert len(forward) == 1
    assert forward[0].observation_id == reverse[0].observation_id
    assert forward[0].battery_instance == 0


def test_same_filename_and_date_do_not_merge_distinct_source_sessions(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    sources = ("1" * 64, "2" * 64)
    _associate_sources(pack_store, "Pack A", sources)
    history.add_observations(
        [
            _event(sources[0], "same-name.bin", 2_000_000),
            _event(sources[1], "same-name.bin", 3_000_000),
        ]
    )

    output = _render(monkeypatch, capsys, pack_store, history)
    summary_rows = _section_rows(output, SUMMARY_HEADING)

    assert len(summary_rows) == 2
    assert [row[1] for row in summary_rows] == [
        "same-name.bin",
        "same-name.bin",
    ]
    assert summary_rows[0][0] == summary_rows[1][0] == "2018-05-06"


def test_current_ownership_filters_before_summary_and_reassignment_adds_session(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    selected = "1" * 64
    reassigned = "2" * 64
    pack_store.create_and_associate(selected, "Pack A")
    pack_store.create_and_associate(reassigned, "Pack B")
    history.add_observations(
        [
            _event(selected, "selected.bin", 2_000_000),
            _event(reassigned, "reassigned.bin", 2_000_000),
            _event(reassigned, "reassigned.bin", 3_000_000),
        ]
    )
    original_history = history.path.read_bytes()

    before = _render(monkeypatch, capsys, pack_store, history)
    assert len(_section_rows(before, SUMMARY_HEADING)) == 1
    assert len(_section_rows(before, ALL_HEADING)) == 1
    assert "reassigned.bin" not in before

    pack_store.associate(reassigned, "Pack A")
    after = _render(monkeypatch, capsys, pack_store, history)

    assert len(_section_rows(after, SUMMARY_HEADING)) == 2
    assert len(_section_rows(after, ALL_HEADING)) == 3
    assert "reassigned.bin" in after
    assert history.path.read_bytes() == original_history


def test_report_uses_current_ownership_and_survives_without_bins(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    selected = "1" * 64
    other = "2" * 64
    not_tracked = "3" * 64
    unseen = "4" * 64
    pack_store.create_and_associate(selected, "Pack A")
    pack_store.create_and_associate(other, "Pack B")
    pack_store.mark_not_tracked(not_tracked)
    full_source_name = (
        "Piper-Cub-2026-10-12-very-long-session-name-with-full-provenance.bin"
    )
    history.add_observations(
        [
            _observation(
                source_sha256=selected,
                source_filename=full_source_name,
                pack_id="Old ingest name",
            ),
            _observation(
                source_sha256=other,
                source_filename="other.bin",
                pack_id="Pack A",
            ),
            _observation(
                source_sha256=not_tracked,
                source_filename="not-tracked.bin",
            ),
            _observation(
                source_sha256=unseen,
                source_filename="unseen.bin",
            ),
        ]
    )
    original_history = history.path.read_bytes()
    _inputs(monkeypatch, "1")

    BatteryPackPerformancePresentation(pack_store, history).run()
    output = capsys.readouterr().out

    assert f"Source: {full_source_name}" in output
    assert "other.bin" not in output
    assert "not-tracked.bin" not in output
    assert "unseen.bin" not in output
    assert len(_section_rows(output, SUMMARY_HEADING)) == 1
    assert len(_section_rows(output, ALL_HEADING)) == 1
    assert history.path.read_bytes() == original_history


def test_reassignment_and_rename_change_membership_without_history_rewrite(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    first = "1" * 64
    second = "2" * 64
    pack_store.create_and_associate(first, "Pack A")
    pack_store.create_and_associate(second, "Pack B")
    history.add_observations(
        [
            _observation(
                source_sha256=first,
                source_filename="first.bin",
                pack_id="Pack A",
            ),
            _observation(
                source_sha256=second,
                source_filename="second.bin",
                pack_id="Pack B",
            ),
        ]
    )
    original_history = history.path.read_bytes()

    pack_store.associate(second, "Pack A")
    pack_store.rename_pack("Pack A", "Pack Renamed")
    _inputs(monkeypatch, "1")
    BatteryPackPerformancePresentation(pack_store, history).run()
    output = capsys.readouterr().out

    assert "Pack ID: Pack Renamed" in output
    assert "first.bin" in output
    assert "second.bin" in output
    assert len(_section_rows(output, SUMMARY_HEADING)) == 2
    assert len(_section_rows(output, ALL_HEADING)) == 2
    assert history.path.read_bytes() == original_history


def test_report_headings_ordering_and_unavailable_rendering(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    early_source = "1" * 64
    later_source = "2" * 64
    unavailable_a = "3" * 64
    unavailable_b = "4" * 64
    for index, source in enumerate(
        (early_source, later_source, unavailable_a, unavailable_b)
    ):
        if index == 0:
            pack_store.create_and_associate(source, "Pack A")
        else:
            pack_store.associate(source, "Pack A")

    early = dataclasses.replace(
        _observation(
            source_sha256=early_source,
            source_filename="early.bin",
        ),
        recorded_at_utc="2018-04-29T00:00:01.000Z",
        gps_anchor_week=1999,
    )
    later = dataclasses.replace(
        _observation(
            source_sha256=later_source,
            source_filename="later.bin",
        ),
        recorded_at_utc="2018-05-13T00:00:01.000Z",
        gps_anchor_week=2001,
    )
    unavailable_common = {
        "recorded_at_utc": None,
        "gps_anchor_week": None,
        "gps_anchor_week_ms": None,
        "gps_anchor_time_us": None,
        "gps_instance": None,
        "gps_utc_offset_seconds": None,
        "capacity_used_mah": None,
        "average_current_a": None,
        "peak_current_a": None,
        "pre_load_voltage_v": None,
        "minimum_loaded_voltage_v": None,
        "voltage_sag_v": None,
        "voltage_recovery_v": None,
    }
    unavailable_z = dataclasses.replace(
        _observation(
            source_sha256=unavailable_a,
            source_filename="z-undated.bin",
        ),
        **unavailable_common,
    )
    unavailable_a_row = dataclasses.replace(
        _observation(
            source_sha256=unavailable_b,
            source_filename="a-undated.bin",
        ),
        **unavailable_common,
    )
    history.add_observations(
        [later, unavailable_z, early, unavailable_a_row]
    )
    _inputs(monkeypatch, "1")

    BatteryPackPerformancePresentation(pack_store, history).run()
    output = capsys.readouterr().out

    assert output.count(SUMMARY_HEADING) == 1
    assert output.count(ALL_HEADING) == 1
    summary_rows = _section_rows(output, SUMMARY_HEADING)
    full_rows = _section_rows(output, ALL_HEADING)
    assert len(summary_rows) == 4
    assert len(full_rows) == 4
    assert output.index("early.bin") < output.index("later.bin")
    assert output.index("later.bin") < output.index("a-undated.bin")
    assert output.index("a-undated.bin") < output.index("z-undated.bin")
    assert [row[0] for row in summary_rows[-2:]] == [
        "Unavailable",
        "Unavailable",
    ]
    assert [row[1] for row in summary_rows[-2:]] == [
        "a-undated.bin",
        "z-undated.bin",
    ]
    undated_row = next(row for row in summary_rows if row[1] == "a-undated.bin")
    assert undated_row.count("Unavailable") >= 7
    for prohibited in (
        "Health",
        "Resistance",
        "Diagnosis",
        "Trend score",
        "Comparability",
    ):
        assert prohibited not in output


def test_report_clearly_handles_pack_without_observations(
    monkeypatch, capsys, tmp_path
):
    pack_store, history = _stores(tmp_path)
    pack_store.create_and_associate("1" * 64, "Pack A")
    _inputs(monkeypatch, "1")

    BatteryPackPerformancePresentation(pack_store, history).run()

    assert (
        "No stored AUTO takeoff observations for this Pack ID."
        in capsys.readouterr().out
    )


@pytest.mark.parametrize("failure_point", ["store", "recorder", "save"])
def test_optional_history_failure_does_not_block_normal_analysis(
    monkeypatch, capsys, tmp_path, failure_point
):
    window = FlightWindow(1_000_000, 2_000_000)
    flight_log = FlightLog(flights=[window])
    presentation = BatteryAnalysisPresentation(config=object())
    selected_flight_reached = []
    monkeypatch.setattr(battery, "select_log_input", lambda: [tmp_path / "log.bin"])

    def resolve(_path):
        presentation._resolved_history_context = ("1" * 64, "Pack A")
        return True, "Pack A"

    monkeypatch.setattr(presentation, "_resolve_pack_id", resolve)
    monkeypatch.setattr(
        battery,
        "FlightReader",
        lambda *_args, **_kwargs: SimpleReader(flight_log),
    )

    def select_flight(_flight_log):
        selected_flight_reached.append(True)
        return None

    monkeypatch.setattr(presentation, "_select_flight", select_flight)
    if failure_point == "store":
        monkeypatch.setattr(
            battery,
            "BatteryPackHistoryStore",
            lambda: (_ for _ in ()).throw(RuntimeError("history load failed")),
        )
    else:
        if failure_point == "save":
            class FailingStore:
                def add_observations(self, _observations):
                    raise RuntimeError("history save failed")

            presentation.history_store = FailingStore()
        else:
            class FailingRecorder:
                def __init__(self, _config):
                    pass

                def record(self, *_args):
                    raise RuntimeError("history recorder failed")

            monkeypatch.setattr(
                battery, "BatteryPackHistoryRecorder", FailingRecorder
            )

    presentation.run()
    output = capsys.readouterr().out

    assert selected_flight_reached == [True]
    assert "Normal Battery Analysis will continue." in output


class SimpleReader:
    def __init__(self, flight_log):
        self.flight_log = flight_log

    def read(self):
        return self.flight_log


@pytest.mark.parametrize("ownership", ["not-tracked", "transient", "unseen"])
def test_history_is_not_written_without_persisted_tracked_ownership(
    monkeypatch, tmp_path, ownership
):
    log_path = tmp_path / "log.bin"
    log_path.write_bytes(b"synthetic log")
    window = FlightWindow(1_000_000, 2_000_000)
    flight_log = FlightLog(flights=[window])
    pack_store = BatteryPackStore(tmp_path / "battery_packs.json")
    history_calls = []

    class ForbiddenHistoryStore:
        def __bool__(self):
            return True

        def add_observations(self, _observations):
            history_calls.append(True)

    if ownership == "not-tracked":
        from core.battery_pack_store import fingerprint_log

        pack_store.mark_not_tracked(fingerprint_log(log_path))
        presentation = BatteryAnalysisPresentation(
            config=object(),
            pack_store=pack_store,
            history_store=ForbiddenHistoryStore(),
        )
    elif ownership == "transient":
        presentation = BatteryAnalysisPresentation(
            pack_id="Transient",
            config=object(),
            pack_store=pack_store,
            history_store=ForbiddenHistoryStore(),
        )
    else:
        presentation = BatteryAnalysisPresentation(
            config=object(),
            pack_store=pack_store,
            history_store=ForbiddenHistoryStore(),
        )
        _inputs(monkeypatch, "0")

    monkeypatch.setattr(battery, "select_log_input", lambda: [log_path])
    monkeypatch.setattr(
        battery,
        "FlightReader",
        lambda *_args, **_kwargs: SimpleReader(flight_log),
    )
    monkeypatch.setattr(presentation, "_select_flight", lambda _log: None)

    presentation.run()

    assert history_calls == []
