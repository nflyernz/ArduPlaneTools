"""Portable landmark and RF-evidence tests for CSV-only range walks."""

import csv
from dataclasses import replace
from datetime import datetime, timedelta
import math

import analyse
import analyses.range_walk as presentation
import pytest
from core.edgetx import read_edgetx_csv
from core.range_walk import (
    MarkerCalibration,
    WalkSettings,
    build_walk,
    build_walk_from_landmarks,
    detect_markers,
    interval_evidence,
    settings_comparable,
)


BASE = datetime(2026, 10, 10, 15, 0, 0)
HEADER = ["Date", "Time", "Ele", "RQly(%)", "1RSS(dB)", "2RSS(dB)",
          "RSNR(dB)", "RFMD", "TPWR(mW)", "TQly(%)", "FM"]
LANDMARKS = ("Start", "Gate", "Hill", "Trees", "Turnaround")
SETTINGS = WalkSettings("50 mW", "250 Hz", "2.4 GHz / mode 2", "off")


def _session(tmp_path, *, name="walk.csv", down=1024, holds=(2, 8, 14, 20, 26),
             extra=(), short=(), up=(), unavailable=(), partial=(), ambiguous=(),
             rssi=-90, quality=95, cadence=0.1, header=HEADER,
             rssi_profile=None, quality_profile=None):
    path = tmp_path / name
    rows = []
    count = int(33 / cadence)
    for index in range(count):
        t = round(index * cadence, 3)
        clock = BASE + timedelta(seconds=t)
        ele = 0
        if any(start <= t < start + 2 for start in (*holds, *extra)):
            ele = down
        if any(start <= t < start + 0.4 for start in short):
            ele = down
        if any(start <= t < start + 2.5 for start in up):
            ele = -down
        gap = any(start <= t < end for start, end in unavailable)
        partly = any(start <= t < end for start, end in partial)
        unclear = any(start <= t < end for start, end in ambiguous)
        reported_rssi = rssi_profile(t) if rssi_profile else rssi
        reported_quality = quality_profile(t) if quality_profile else quality
        row = {
            "Date": clock.strftime("%Y-%m-%d"),
            "Time": clock.strftime("%H:%M:%S.%f")[:-3],
            "Ele": ele, "RQly(%)": 0 if gap or partly or unclear else reported_quality,
            "1RSS(dB)": 0 if gap or partly or unclear else reported_rssi,
            "2RSS(dB)": 0, "RSNR(dB)": 0 if gap or partly or unclear else -2,
            "RFMD": 2 if partly else 0 if gap or unclear else 2,
            "TPWR(mW)": 50 if partly else 0 if gap or unclear else 50,
            "TQly(%)": 0 if gap or unclear else 70,
            "FM": "MANU" if unclear else "",
        }
        rows.append(row)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows([[row.get(field, "") for field in header] for row in rows])
    return read_edgetx_csv(path)


def _walk(session, *, selected=(1, 2, 3, 4, 5), baseline=False,
          down=1024, label="Original", settings=SETTINGS):
    return build_walk(session, label, label + " antenna", settings,
                      MarkerCalibration(down, 0), selected, baseline=baseline)


def test_local_stick_markers_reject_short_up_and_survive_rf_gap(tmp_path):
    session = _session(tmp_path, short=(5,), up=(31,), unavailable=((14, 17),))
    markers = detect_markers(session, MarkerCalibration(1024, 0))

    assert len(markers) == 5
    assert [marker.onset for marker in markers] == [
        BASE + timedelta(seconds=t) for t in (2, 8, 14, 20, 26)]
    assert markers[2].release == BASE + timedelta(seconds=16)
    assert session.rows[145].availability == "unavailable"
    assert session.rows[145].ele == 1024


def test_model_specific_reversed_sign_and_variable_cadence(tmp_path):
    session = _session(tmp_path, down=-1024, cadence=0.15, up=(30,))
    markers = detect_markers(session, MarkerCalibration(-1024, 0))
    assert len(markers) == 5
    # Wrong sign would pick the deliberate full-up hold, hence calibration is required.
    wrong_sign = detect_markers(session, MarkerCalibration(1024, 0))
    assert len(wrong_sign) == 1
    assert wrong_sign[0].onset == BASE + timedelta(seconds=30)
    assert MarkerCalibration(-1024, 0, near_down=-900).is_down(-900)
    assert not MarkerCalibration(-1024, 0, near_down=-900).is_down(-899)
    with pytest.raises(ValueError, match="between neutral and down"):
        MarkerCalibration(-1024, 0, near_down=900)


def test_marker_neutral_return_tolerance_is_configurable(tmp_path):
    session = _session(tmp_path, holds=(2,))
    # After the hold, 300 is inside a 33% neutral band for a 1024 span, but
    # outside the established 20% default. Delay the next exact-neutral row.
    for index in range(40, 51):
        session.rows[index] = replace(session.rows[index], ele=300)

    default = detect_markers(session, MarkerCalibration(1024, 0))
    gui_preview = detect_markers(
        session,
        MarkerCalibration(1024, 0, neutral_tolerance=0.33),
    )

    assert default == ()
    assert len(gui_preview) == 1
    assert gui_preview[0].release == BASE + timedelta(seconds=4)


def test_five_explicit_landmarks_extra_candidate_and_missing_boundaries(tmp_path):
    session = _session(tmp_path, extra=(23,))
    walk = _walk(session, selected=(1, 2, 3, 4, 6), baseline=True)
    assert len(walk.candidates) == 6
    assert len(walk.sections) == 4
    assert walk.sections[0].start == BASE + timedelta(seconds=4)
    assert walk.sections[0].end == BASE + timedelta(seconds=8)
    assert walk.holds[0].duration_s == 2
    assert all(section.end <= walk.landmarks[-1].onset for section in walk.sections)
    with pytest.raises(ValueError, match="five confirmed"):
        _walk(session, selected=(1, 2, None, 4, 6), baseline=True)
    with pytest.raises(ValueError, match="distinct, increasing"):
        _walk(session, selected=(1, 2, 2, 4, 6))
    incomplete = _walk(session, selected=(1, 2, None, 4, 6))
    assert incomplete.sections[1:3] == (None, None)
    assert incomplete.sections[0] is not None


def test_confirmed_landmark_reconstruction_matches_detected_walk(tmp_path):
    session = _session(tmp_path, unavailable=((17, 18),))
    detected = _walk(session, baseline=True)

    reconstructed = build_walk_from_landmarks(
        session,
        detected.label,
        detected.antenna,
        detected.settings,
        detected.candidates,
        detected.landmarks,
    )

    assert reconstructed == detected
    with pytest.raises(ValueError, match="five landmark positions"):
        build_walk_from_landmarks(
            session,
            detected.label,
            detected.antenna,
            detected.settings,
            detected.candidates,
            detected.landmarks[:4],
        )


def test_unavailable_partial_ambiguous_and_valid_zero_are_distinct(tmp_path):
    session = _session(tmp_path, unavailable=((4, 5),), partial=((5, 5.5),),
                       ambiguous=((5.5, 6),))
    # A real zero quality with negative receiver RSSI remains eligible.
    row = session.rows[65]
    row.values["RQly(%)"] = 0
    section = interval_evidence(session, BASE + timedelta(seconds=4),
                                BASE + timedelta(seconds=8))

    assert section.availability_counts["unavailable"] == 10
    assert section.availability_counts["partial"] == 5
    assert section.availability_counts["ambiguous"] == 5
    assert section.usable_counts["1RSS(dB)"] == 20
    assert section.usable_counts["RQly(%)"] == 20
    assert section.p10_values["1RSS(dB)"] == -90
    assert section.p10_values["RQly(%)"] == pytest.approx(95)
    assert section.longest_unavailable_s == pytest.approx(1.0)
    assert section.rssi_coverage == pytest.approx(0.5)
    assert section.tqly_median == 70
    assert row.observed("RQly(%)") == 0


def test_fully_missing_section_is_not_zero_signal(tmp_path):
    session = _session(tmp_path, unavailable=((4, 8),))
    walk = _walk(session, baseline=True)
    section = walk.sections[0]
    assert section.row_count == 40
    assert section.usable_counts["1RSS(dB)"] == 0
    assert section.p10_values["1RSS(dB)"] is None
    assert section.median_values["RQly(%)"] is None
    assert section.rssi_coverage == 0
    report = presentation.format_range_walk_report([walk, _walk(session)], LANDMARKS,
                                                    "Farm gate")
    assert "Unavailable" in report
    assert "1→2 | Walk 1 baseline | Unavailable" in report
    assert " | 0.0 dBm" not in report


def test_logged_value_p10_and_unlogged_time_are_explicit(tmp_path):
    session = _session(tmp_path)
    for index in range(40, 60):
        session.rows[index].values["1RSS(dB)"] = -110
    for index in range(60, 80):
        session.rows[index].values["1RSS(dB)"] = -80
    section = interval_evidence(session, BASE + timedelta(seconds=4),
                                BASE + timedelta(seconds=8))
    assert section.median_values["1RSS(dB)"] == -95
    assert section.p10_values["1RSS(dB)"] == -110
    assert section.usable_counts["1RSS(dB)"] == 40

    # A recording interruption is unlogged time, not an RF-unavailable row.
    session.rows = [row for row in session.rows
                    if not BASE + timedelta(seconds=5) <= row.clock <
                    BASE + timedelta(seconds=6)]
    interrupted = interval_evidence(session, BASE + timedelta(seconds=4),
                                    BASE + timedelta(seconds=8))
    assert interrupted.row_count == 30
    assert interrupted.unlogged_time_s >= 0.9
    assert interrupted.availability_counts["unavailable"] == 0


def test_baseline_is_walk_one_for_both_later_walks_and_settings_are_qualified(tmp_path):
    first = _walk(_session(tmp_path, name="first.csv", rssi=-90), baseline=True)
    second = _walk(_session(tmp_path, name="second.csv", rssi=-80), label="Vertical")
    third = _walk(_session(tmp_path, name="third.csv", rssi=-100), label="Under wing")
    assert settings_comparable(first, second)
    report = presentation.format_range_walk_report([first, second, third], LANDMARKS,
                                                    "Fence corner")
    section = report.split("Section comparison", 1)[1].split("Section and landmark", 1)[0]
    assert section.index("Walk 1 baseline") < section.index("Walk 2") < section.index("Walk 3")
    assert "Walk 1 is the original-antenna baseline for every comparison" in report
    changed = _walk(_session(tmp_path, name="changed.csv", rssi=-70),
                    settings=WalkSettings("100 mW", "250 Hz", "2.4 GHz / mode 2", "off"))
    assert not settings_comparable(first, changed)
    assert "Not like-for-like" in presentation.format_range_walk_report(
        [first, changed], LANDMARKS, "Fence corner")


def test_missing_or_non_numeric_ele_is_rejected_for_marker_detection(tmp_path):
    missing = _session(tmp_path, name="missing.csv", header=[x for x in HEADER if x != "Ele"])
    duplicated = _session(tmp_path, name="duplicate.csv", header=[*HEADER, "Ele"])
    malformed = _session(tmp_path, name="malformed.csv")
    malformed.rows[10] = replace(malformed.rows[10], ele=None)
    for session in (missing, duplicated, malformed):
        with pytest.raises(ValueError, match="one numeric Ele"):
            detect_markers(session, MarkerCalibration(1024, 0))


def test_graphs_export_png_with_explicit_gap_breaks(tmp_path):
    first = _walk(_session(tmp_path, name="first.csv", unavailable=((4, 8),)),
                  baseline=True)
    second = _walk(_session(tmp_path, name="second.csv", rssi=-80))
    xs, ys = presentation._trace_points(first.session.rows, "1RSS(dB)", 0.1,
                                         first.session.rows[0].clock)
    assert len(xs) == len(ys)
    assert math.isnan(ys[45])
    assert all(value is None or value < 0 for value in
               (first.session.rows[45].observed("1RSS(dB)"),))
    paths = presentation.write_range_walk_graphs([first, second], LANDMARKS,
                                                  tmp_path / "graphs")
    assert len(paths) == 3
    assert all(path.suffix == ".png" and path.stat().st_size > 1000 for path in paths)


def test_fluctuating_rf_graphs_share_rssi_scale_and_keep_real_gaps(
        monkeypatch, tmp_path):
    import matplotlib.pyplot as plt
    from PIL import Image

    def first_rssi(t):
        if 4.5 <= t < 5.1:
            return -112
        if 22 <= t < 22.6:
            return -108
        return -90 - int(t) % 4

    def first_quality(t):
        if 4.5 <= t < 5.1:
            return 15
        if 22 <= t < 22.6:
            return 25
        return 90 + int(t) % 7

    first = _walk(_session(tmp_path, name="varying_1.csv",
                           rssi_profile=first_rssi,
                           quality_profile=first_quality,
                           unavailable=((17, 18),)), baseline=True)
    second = _walk(_session(tmp_path, name="varying_2.csv",
                            rssi_profile=lambda t: -83 - int(t) % 10,
                            quality_profile=lambda t: 85 + int(t) % 10,
                            unavailable=((18, 18.5),)))
    assert len(first.candidates) == 5
    assert first.sections[0].p10_values["1RSS(dB)"] == -112
    assert first.sections[0].p10_values["RQly(%)"] == 15
    assert first.sections[2].availability_counts["unavailable"] == 10

    figures = []
    actual_close = plt.close
    monkeypatch.setattr(plt, "close", lambda fig: figures.append(fig))
    try:
        paths = presentation.write_range_walk_graphs(
            [first, second], LANDMARKS, tmp_path / "fluctuating_graphs")
        assert len(figures) == 3
        assert figures[0].axes[0].get_ylim() == figures[1].axes[0].get_ylim()
        assert figures[0].axes[1].get_ylim() == (-2, 102)
        rssi_trace = figures[0].axes[0].lines[0].get_ydata()
        quality_trace = figures[0].axes[1].lines[0].get_ydata()
        assert -112 in rssi_trace and -90 in rssi_trace
        assert 15 in quality_trace and 96 in quality_trace
        assert any(math.isnan(value) for value in rssi_trace)
        assert any(math.isnan(value) for value in quality_trace)
        assert {label.get_text() for label in figures[0].axes[0].texts} == {
            "1", "2", "3", "4", "5"}
        assert "turnaround" in figures[0].texts[1].get_text().casefold()
        comparison = figures[2]
        assert len(comparison.axes) == 2
        assert comparison.axes[0].get_xlim()[1] > 3
        assert comparison.axes[1].get_ylim() == (-2, 102)
        assert len(comparison.axes[0].lines) == 2
        assert len(comparison.axes[1].lines) == 2
        assert [line.get_color() for line in comparison.axes[0].lines] == [
            line.get_color() for line in comparison.axes[1].lines
        ]
        assert list(comparison.axes[0].lines[0].get_ydata()) == [
            section.p10_values["1RSS(dB)"] for section in first.sections
        ]
        assert list(comparison.axes[1].lines[0].get_ydata()) == [
            section.p10_values["RQly(%)"] for section in first.sections
        ]
        assert (
            "metric-specific observed-time coverage"
            in comparison.texts[-1].get_text()
        )
        for path in paths:
            with Image.open(path) as image:
                assert image.width == 1200
                assert image.height <= 700
    finally:
        for figure in figures:
            actual_close(figure)


def test_section_comparison_does_not_plot_unavailable_metrics_as_zero(
        monkeypatch, tmp_path):
    import matplotlib.pyplot as plt

    first = _walk(
        _session(tmp_path, name="unavailable.csv", unavailable=((4, 8),)),
        baseline=True,
    )
    second = _walk(_session(tmp_path, name="available.csv", rssi=-80))
    figures = []
    actual_close = plt.close
    monkeypatch.setattr(plt, "close", lambda figure: figures.append(figure))
    try:
        presentation.write_range_walk_graphs(
            [first, second], LANDMARKS, tmp_path / "unavailable_graphs"
        )
        comparison = figures[2]
        assert math.isnan(comparison.axes[0].lines[0].get_ydata()[0])
        assert math.isnan(comparison.axes[1].lines[0].get_ydata()[0])
        assert 0 not in comparison.axes[0].lines[0].get_ydata()
        assert 0 not in comparison.axes[1].lines[0].get_ydata()
    finally:
        for figure in figures:
            actual_close(figure)


def test_menu_dispatches_separate_range_walk_entry(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(presentation.RangeWalkComparisonPresentation, "run",
                        lambda self: calls.append("range walk"))
    choices = iter(("12", "0"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))
    analyse.menu()
    assert calls == ["range walk"]
    assert "12. Radio Link Range-Walk Comparison" in capsys.readouterr().out


def test_cli_confirms_baseline_route_and_exports_report_and_graphs(
        monkeypatch, tmp_path, capsys):
    first = _session(tmp_path, name="first.csv")
    second = _session(tmp_path, name="second.csv", rssi=-80)
    output = tmp_path / "output"
    answers = iter((
        "2", str(first.path), "Original mount", "Original antenna", "y",
        "50 mW", "250 Hz", "2.4 GHz / mode 2", "off", "1024", "0", "900",
        "1,2,3,4,5", *LANDMARKS, "Fence corner",
        str(second.path), "Vertical mount", "Vertical antenna",
        "50 mW", "250 Hz", "2.4 GHz / mode 2", "off", "1024", "0", "900",
        "1,2,3,4,5", str(output),
    ))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    presentation.RangeWalkComparisonPresentation().run()

    shown = capsys.readouterr().out
    assert "Walk 1 is the original-antenna baseline" in shown
    assert "Safe turnaround: Fence corner" in shown
    assert "1→2 | Walk 1 baseline" in shown
    assert (output / "walk_1_rf.png").is_file()
    assert (output / "walk_2_rf.png").is_file()
    assert (output / "section_1rss_p10.png").is_file()


def test_cli_can_cancel_during_initial_setup_without_output(
        monkeypatch, capsys):
    generated = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": "q")
    monkeypatch.setattr(
        presentation,
        "format_range_walk_report",
        lambda *_args: generated.append("report"),
    )
    monkeypatch.setattr(
        presentation,
        "write_range_walk_graphs",
        lambda *_args: generated.append("graphs"),
    )

    presentation.RangeWalkComparisonPresentation().run()

    output = capsys.readouterr().out
    assert "Range-Walk Comparison cancelled." in output
    assert "Range-Walk Comparison unavailable:" not in output
    assert generated == []


def test_cli_can_cancel_during_walk_retry_without_output(
        monkeypatch, tmp_path, capsys):
    answers = iter(("2", str(tmp_path / "missing.csv"), "q"))
    generated = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(
        presentation,
        "format_range_walk_report",
        lambda *_args: generated.append("report"),
    )
    monkeypatch.setattr(
        presentation,
        "write_range_walk_graphs",
        lambda *_args: generated.append("graphs"),
    )

    presentation.RangeWalkComparisonPresentation().run()

    output = capsys.readouterr().out
    assert "Walk 1 input skipped with reason:" in output
    assert "Range-Walk Comparison cancelled." in output
    assert "Range-Walk Comparison unavailable:" not in output
    assert generated == []


def test_identical_csv_copies_have_same_source_identity(tmp_path):
    first = _session(tmp_path, name="first.csv")
    copy = tmp_path / "copy.csv"
    copy.write_bytes(first.path.read_bytes())
    assert presentation._csv_fingerprint(first.path) == presentation._csv_fingerprint(copy)
