"""Portable presentation, cohort and CLI contracts for Stall Analysis."""

from dataclasses import replace
from pathlib import Path

import analyse

from analyses import stall as presentation
from core.stall_test import AirspeedQuality, StallFlightResult, StallReason, StallStatus
from test_stall_characterization import _matched
from test_stall_test import _log, _one


def _probable():
    log, window = _log()
    return _one(_matched(log), window), window


def _flight(window, *results):
    return StallFlightResult(window, results, "fbwa-prototype-1")


def _with_peak_speed(result, speed, **changes):
    air = result.airspeed
    peak = air.raw_airspeed_at_pre_fall_pitch_peak
    peak = replace(peak, sample=replace(peak.sample, value=speed), **changes)
    return replace(result, airspeed=replace(
        air, raw_airspeed_at_pre_fall_pitch_peak=peak,
    ))


def test_elapsed_time_uses_minutes_and_hours_without_losing_milliseconds():
    assert presentation._time(0) == "00:00.000"
    assert presentation._time(59_999_000) == "00:59.999"
    assert presentation._time(60_000_000) == "01:00.000"
    assert presentation._time(3_599_999_000) == "59:59.999"
    assert presentation._time(3_599_999_500) == "1:00:00.000"
    assert presentation._time(3_600_000_000) == "1:00:00.000"
    assert presentation._time(3_804_125_000) == "1:03:24.125"


def test_probable_attempt_uses_conservative_response_and_distinct_speed_labels():
    result, _ = _probable()
    report = presentation.format_stall_attempt(result, 3)
    assert "Attempt 3 |" in report
    assert "Probable demand-opposed attitude departure" in report
    assert "FBWA" in report
    assert "pilot nose-up RCIN" in report
    assert "FBWA target" in report and "actual pitch" in report
    assert "target−actual error" in report
    assert "Logged elevator command/output endpoint" in report
    assert "command 4500; output 1900 PWM (channel 2)" in report
    assert "AETR.Elev" not in report and "RCOU.C" not in report
    assert "Pre-fall pitch-peak airspeed" in report
    assert "First opposed-fall airspeed" in report
    assert "Minimum usable airspeed" in report
    assert "Recovery-control-start airspeed" in report
    assert "raw ARSP" in report
    assert "event/sample gap" in report
    assert "logged " not in next(line for line in report.splitlines()
                                 if "Pre-fall pitch-peak airspeed" in line)
    assert "Stall speed" not in report
    assert "servo saturation" not in report.casefold()


def test_negative_ambiguous_rejected_and_unavailable_attempts():
    negative = _one(*_log(profile="steady", endpoint=False))
    ambiguous = _one(*_log(profile="weak"))
    rejected = _one(*_log(pulls=((0.2, 0.5),), endpoint=False))
    absent = _one(*_log(speed="missing"))
    assert "No demonstrated departure" in presentation.format_stall_attempt(negative, 1)
    assert "Minimum usable airspeed" in presentation.format_stall_attempt(negative, 1)
    assert "Ambiguous" in presentation.format_stall_attempt(ambiguous, 2)
    assert "Attempt 2 |" in presentation.format_stall_attempt(ambiguous, 2)
    assert "Rejected candidate" in presentation.format_stall_attempt(rejected, 3)
    assert "short movement" in presentation.format_stall_attempt(rejected, 3)
    text = presentation.format_stall_attempt(absent, 4)
    assert "unavailable" in text
    assert "0.00 m/s" not in text


def test_saved_effective_and_unsupported_ratio_warning_are_distinct():
    result, _ = _probable()
    report = presentation.format_stall_attempt(result, 1)
    assert "Saved airspeed ratio 2.6500" in report
    assert "Effective airspeed ratio 2.0000" in report
    assert "AUTOCAL off" in report
    assert report.count("Calibration:") == 1
    assert "Airspeed note:" not in report
    air = result.airspeed
    peak = replace(
        air.raw_airspeed_at_pre_fall_pitch_peak,
        effective_ratio=None,
        warnings=("effective ratio unsupported for firmware/sensor configuration",),
    )
    unsupported = replace(result, airspeed=replace(
        air, raw_airspeed_at_pre_fall_pitch_peak=peak,
    ))
    text = presentation.format_stall_attempt(unsupported, 1)
    assert "Effective airspeed ratio unavailable (unsupported)" in text
    assert "Airspeed note:" in text
    assert "Effective airspeed ratio 2.6500" not in text


def test_suspect_event_speed_is_unavailable_and_not_printed_as_stall_speed():
    result, _ = _probable()
    peak = result.airspeed.raw_airspeed_at_pre_fall_pitch_peak
    suspect = replace(peak, quality=AirspeedQuality.SUSPECT,
                      warnings=("sensor not logged healthy",))
    result = replace(result, airspeed=replace(
        result.airspeed, raw_airspeed_at_pre_fall_pitch_peak=suspect,
    ))
    report = presentation.format_stall_attempt(result, 1)
    assert "Pre-fall pitch-peak airspeed: unavailable" in report
    assert "sensor not logged healthy" in report
    assert "Effective airspeed ratio unavailable (unusable ARSP evidence)" in report
    assert "Stall speed" not in report
    compact = presentation.format_stall_attempt(result, 1, compact_notable=True)
    assert "pre-fall peak unavailable (sensor not logged healthy)" in compact
    assert "Airspeed note: sensor not logged healthy" not in compact


def test_recovery_reports_observations_without_claiming_completion():
    result, _ = _probable()
    report = presentation.format_stall_attempt(result, 1)
    assert "Recovery control at" in report
    assert "Minimum measured pitch after control action" in report
    assert "Recovered successfully" not in report
    assert "Recovery complete" not in report


def test_pitch_limit_interaction_is_neutral_and_missing_recovery_is_explicit():
    result, _ = _probable()
    recovery = result.recovery
    at_min = recovery.pitch_minimum.time_us
    recovery = replace(
        recovery,
        pitch_minimum=replace(recovery.pitch_minimum, value=-15),
        target_at_pitch_minimum=replace(
            recovery.target_at_pitch_minimum, value=-8,
        ),
        pitch_limit_min_deg=-10, attitude_below_target_limit=True,
        nose_up_elevator_command=replace(
            result.departure.aetr_endpoint, time_us=at_min,
        ),
        nose_up_elevator_pwm_command=replace(
            result.departure.rcou_endpoint, time_us=at_min,
        ),
    )
    report = presentation.format_stall_attempt(
        replace(result, recovery=recovery), 1,
    )
    assert "Attitude exceeded negative target limit" in report
    assert "nose-up correction" in report
    assert "prevented recovery" not in report
    absent = presentation.format_stall_attempt(
        replace(result, recovery=None), 1,
    )
    assert "Recovery-control action: not observed" in absent


def test_same_flight_summary_mean_median_range_and_numbered_members():
    result, window = _probable()
    flight = _flight(window, *(
        _with_peak_speed(result, value) for value in (8.0, 10.0, 12.0)
    ))
    summary = presentation.summarize_clean_idle_airspeed(flight)
    assert summary.attempt_numbers == (1, 2, 3)
    assert (summary.count, summary.mean_m_s, summary.median_m_s,
            summary.minimum_m_s, summary.maximum_m_s) == (3, 10, 10, 8, 12)
    report = presentation.format_stall_flight_report(flight, 1)
    assert "Comparable clean-idle probable departures: 3" in report
    assert "Mean pre-fall pitch-peak airspeed: 10.00 m/s" in report
    assert "Median: 10.00 m/s; range: 8.00–12.00 m/s" in report
    assert "Stall speed =" not in report
    assert "non-departure bookend" not in report


def test_routine_flight_counts_negatives_and_rejections_but_expands_notable_events():
    result, window = _probable()
    ambiguous = replace(result, status=StallStatus.AMBIGUOUS)
    negative = replace(result, status=StallStatus.NO_DEMONSTRATED_DEPARTURE)
    rejected = replace(result, status=StallStatus.REJECTED)
    flight = _flight(window, result, ambiguous, negative, rejected)
    report = presentation.format_stall_flight_report(flight, 2)
    assert "Stall-test series detected" not in report
    assert "Probable departures: 1" in report
    assert "Ambiguous attempts: 1" in report
    assert "No demonstrated departures: 1" in report
    assert "Rejected candidates: 1" in report
    assert "Notable events:" in report
    assert "Attempt 1 |" in report and "Attempt 2 |" in report
    assert "Attempt 3 |" not in report and "Candidate 4 |" not in report
    assert "Minimum usable airspeed" in report
    assert "Recovery observations" not in report
    assert "Later recovery speed milestone" not in report
    assert "Recovery observation: control at" in report
    assert "AETR.Elev" not in report and "RCOU.C" not in report
    probable_lines = presentation.format_stall_attempt(
        result, 1, compact_notable=True,
    ).splitlines()
    ambiguous_lines = presentation.format_stall_attempt(
        ambiguous, 2, compact_notable=True,
    ).splitlines()
    assert len(probable_lines) <= 10
    assert len(ambiguous_lines) <= 6
    assert not any(line.strip() in {"Departure", "Airspeed", "Recovery observations"}
                   for line in probable_lines + ambiguous_lines)


def test_series_keeps_negative_evidence_and_hoists_unchanged_calibration():
    result, window = _probable()
    negative = replace(
        result, status=StallStatus.NO_DEMONSTRATED_DEPARTURE,
        reasons=(StallReason.EVIDENCE_GAP,),
    )
    rejected = replace(result, status=StallStatus.REJECTED)
    flight = _flight(window, result, negative, result, rejected)
    summary = presentation.summarize_clean_idle_airspeed(flight)
    report = presentation.format_stall_flight_report(flight, 3)
    assert summary.attempt_numbers == (1, 3)
    assert "Stall-test series detected" in report
    assert "Attempt 2 |" in report and "No demonstrated departure" in report
    assert "Minimum usable airspeed" in report
    assert "Evidence notes: evidence gap" in report
    assert "  Departure\n" in report
    assert "  Airspeed\n" in report
    assert "  Recovery observations\n" in report
    assert "First opposed-fall airspeed" in report
    assert "Minimum measured pitch after control action" in report
    assert "Candidate 4 |" not in report
    assert "Rejected candidates: 1" in report
    assert report.count("Calibration:") == 1
    assert "Comparable clean-idle probable departures: 2 (attempts 1, 3)" in report
    assert f"Mean pre-fall pitch-peak airspeed: {summary.mean_m_s:.2f} m/s" in report


def test_departure_reference_altitude_is_reported_only_when_core_provides_it():
    result, window = _probable()
    altitude = replace(
        result.response.pitch_peak, source="BARO", field="Alt", value=85.5,
    )
    with_altitude = replace(result, recovery=replace(
        result.recovery, altitude_at_departure_reference=altitude,
    ))
    detailed = presentation.format_stall_flight_report(
        _flight(window, with_altitude, with_altitude), 1,
    )
    compact = presentation.format_stall_flight_report(
        _flight(window, with_altitude), 1,
    )
    expected = "Altitude at departure reference: 85.50 m BARO (sample 00:01.900)"
    assert expected in detailed and expected in compact
    unavailable = replace(result, recovery=replace(
        result.recovery, altitude_at_departure_reference=None,
    ))
    assert "Altitude at departure reference" not in presentation.format_stall_attempt(
        unavailable, 1,
    )
    assert "Altitude at departure reference" not in presentation.format_stall_flight_report(
        _flight(window, unavailable), 1,
    )
    ambiguous = replace(result, status=StallStatus.AMBIGUOUS, recovery=None)
    assert "Altitude at departure reference" not in presentation.format_stall_attempt(
        ambiguous, 1, compact_notable=True,
    )


def test_series_calibration_change_remains_visible_on_compact_negative():
    result, window = _probable()
    changed = _with_peak_speed(result, 9.0, effective_ratio=2.2)
    changed = replace(changed, status=StallStatus.NO_DEMONSTRATED_DEPARTURE)
    report = presentation.format_stall_flight_report(
        _flight(window, result, changed, result), 1,
    )
    assert "Stall-test series detected" in report
    assert "Attempt 2 |" in report
    assert "Effective airspeed ratio 2.2000" in report
    assert "Effective airspeed ratio 2.0000" in report
    assert report.count("Calibration:") == 3


def test_matching_ratio_does_not_hoist_changed_airspeed_provenance():
    result, window = _probable()
    peak = result.airspeed.raw_airspeed_at_pre_fall_pitch_peak
    sample_parameters = replace(
        peak.saved_parameters_at_sample,
        values={**peak.saved_parameters_at_sample.values, "ARSPD_OFFSET": 3.0},
    )
    changed = replace(
        result, status=StallStatus.NO_DEMONSTRATED_DEPARTURE,
        airspeed=replace(
            result.airspeed,
            raw_airspeed_at_pre_fall_pitch_peak=replace(
                peak, saved_parameters_at_sample=sample_parameters,
            ),
        ),
    )
    report = presentation.format_stall_flight_report(
        _flight(window, result, changed, result), 1,
    )
    assert "Stall-test series detected" in report
    assert report.count("Calibration:") == 3


def test_powered_banked_ambiguous_negative_and_unusable_are_excluded():
    result, window = _probable()
    powered = replace(result, context=replace(
        result.context, clean_idle_context=False,
        throttle_class="powered_or_variable_command", bank_class="banked",
    ))
    ambiguous = replace(result, status=StallStatus.AMBIGUOUS)
    negative = replace(result, status=StallStatus.NO_DEMONSTRATED_DEPARTURE)
    suspect_peak = replace(
        result.airspeed.raw_airspeed_at_pre_fall_pitch_peak,
        quality=AirspeedQuality.SUSPECT,
    )
    unusable = replace(result, airspeed=replace(
        result.airspeed, raw_airspeed_at_pre_fall_pitch_peak=suspect_peak,
    ))
    flight = _flight(
        window, result, powered, ambiguous, negative, unusable,
        _with_peak_speed(result, 10.0),
    )
    summary = presentation.summarize_clean_idle_airspeed(flight)
    assert summary.attempt_numbers == (1, 6)
    assert summary.mean_m_s == (result.airspeed.raw_airspeed_at_pre_fall_pitch_peak.sample.value + 10) / 2
    report = presentation.format_stall_flight_report(flight, 1)
    assert "Probable departures: 4" in report
    assert "No demonstrated departures: 1" in report
    assert "Ambiguous attempts: 1" in report
    assert "Summary exclusion: powered/variable or unknown throttle, banked/unknown attitude" in report
    assert "Summary exclusion: event-linked airspeed or calibration unavailable" in report


def test_one_event_or_zero_eligible_events_has_no_average():
    result, window = _probable()
    assert presentation.summarize_clean_idle_airspeed(_flight(window, result)) is None
    assert presentation.summarize_clean_idle_airspeed(_flight(
        window, replace(result, status=StallStatus.AMBIGUOUS),
    )) is None
    report = presentation.format_stall_flight_report(_flight(window, result), 1)
    assert "no mean reported" in report
    assert "Mean pre-fall pitch-peak airspeed" not in report


def test_material_runtime_ratio_change_suppresses_single_flight_mean():
    result, window = _probable()
    tiny_float_noise = _with_peak_speed(result, 10.0, effective_ratio=2.0000001)
    assert presentation.summarize_clean_idle_airspeed(
        _flight(window, result, tiny_float_noise),
    ).count == 2
    changed = _with_peak_speed(result, 11.0, effective_ratio=2.2)
    assert presentation.summarize_clean_idle_airspeed(
        _flight(window, result, changed),
    ) is None
    report = presentation.format_stall_flight_report(_flight(window, result, changed), 1)
    assert "incompatible airspeed provenance/calibration; no mean reported" in report


def test_empty_and_rejected_only_flights_do_not_claim_no_stalls():
    result, window = _probable()
    empty = presentation.format_stall_flight_report(_flight(window), 1)
    rejected = presentation.format_stall_flight_report(_flight(
        window, replace(result, status=StallStatus.REJECTED),
    ), 2)
    assert "No analyzable FBWA stall-test attempts found." in empty
    assert "No analyzable FBWA stall-test attempts found." in rejected
    assert "No stalls detected" not in empty + rejected


def test_menu_adds_stall_without_reordering_existing_actions(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(
        presentation.StallAnalysisPresentation,
        "run", lambda _self: called.append(True),
    )
    choices = iter(("13", "0"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))
    analyse.menu()
    output = capsys.readouterr().out
    assert called == [True]
    assert "10. Takeoff Analysis" in output
    assert "11. Radio Link Analysis" in output
    assert "12. Radio Link Range-Walk Comparison" in output
    assert "13. Stall Analysis" in output
    assert (
        output.index("10. Takeoff Analysis")
        < output.index("11. Radio Link Analysis")
        < output.index("12. Radio Link Range-Walk Comparison")
        < output.index("13. Stall Analysis")
    )


def test_presentation_uses_shared_selector_and_existing_core(monkeypatch, capsys):
    log, _ = _log()
    _matched(log)
    selected = Path("Logs/synthetic.bin")
    calls = []
    monkeypatch.setattr(presentation, "select_log_input", lambda: [selected])

    class Reader:
        def __init__(self, path, config):
            calls.append((path, config))

        def read(self):
            return log

    monkeypatch.setattr(presentation, "FlightReader", Reader)
    presentation.StallAnalysisPresentation().run()
    assert calls[0][0] == selected
    output = capsys.readouterr().out
    assert "Stall Analysis | FBWA slow-flight evidence" in output
    assert "Log: synthetic.bin" in output
    assert "Flight 1" in output
    assert "Probable demand-opposed attitude departure" in output
