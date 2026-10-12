"""Regression tests for reusable Landing Analysis text presentation."""

from types import SimpleNamespace

from analyses.landing import (
    LandingAnalysis,
    format_landing_flight_result,
    format_landing_log_report,
)


def _attempt_analysis(*, rangefinder=False, unavailable=False, end_reason="gps"):
    value = None if unavailable else 4.25
    time_us = None if unavailable else 2_500_000
    return SimpleNamespace(
        attempt=SimpleNamespace(start_us=1_000_000, end_us=4_000_000),
        duration_s=3.04,
        approach_start_altitude=value,
        glide_slope_degrees=-3.26 if not unavailable else None,
        preflare_time_us=time_us,
        preflare_altitude=value,
        preflare_airspeed=12.34 if not unavailable else None,
        preflare_gps_speed=11.25 if not unavailable else None,
        preflare_sink_rate=-0.66 if not unavailable else None,
        flare_time_us=time_us,
        flare_altitude=1.24 if not unavailable else None,
        flare_sink_rate=-0.44 if not unavailable else None,
        flare_airspeed=10.55 if not unavailable else None,
        flare_gps_speed=9.46 if not unavailable else None,
        flare_distance=7.87 if not unavailable else None,
        rangefinder_first_nonzero_time_us=2_000_000 if rangefinder else None,
        rangefinder_first_nonzero_distance=2.34 if rangefinder else None,
        rangefinder_first_in_range_time_us=None,
        rangefinder_first_in_range_distance=None,
        rangefinder_continuous_time_us=2_200_000 if rangefinder else None,
        gps_stop_time_us=3_500_000 if not unavailable else None,
        flare_to_gps_stop_s=1.04 if not unavailable else None,
        landing_end_target_distance_m=5.55 if not unavailable else None,
        end_reason=end_reason,
    )


def test_flight_formatter_preserves_numbering_sections_precision_and_optional_evidence():
    result = SimpleNamespace(
        report=[
            (1, 1, _attempt_analysis(rangefinder=True)),
            (1, 2, _attempt_analysis(unavailable=True, end_reason="abort")),
            (2, 1, _attempt_analysis(end_reason="flight_window_end")),
        ]
    )

    report = format_landing_flight_result(result, 3)

    assert report.index("Landing 1 Attempt 1") < report.index(
        "Landing 1 Attempt 2"
    ) < report.index("Landing 2 Attempt 1")
    assert "FLIGHT 3" in report
    assert report.count("APPROACH") == 3
    assert report.count("PREFLARE") == 3
    assert report.splitlines().count("FLARE") == 3
    assert report.count("LANDING / ROLLOUT COMPLETION") == 3
    assert report.count("RANGEFINDER") == 1
    assert "First in range              Unavailable" in report
    assert "Landing duration            3.0 s" in report
    assert "Approach altitude           4.2 m" in report
    assert "Glide slope                 -3.3 deg" in report
    assert "Preflare height             Unavailable" in report
    assert "End reason                  Landing aborted" in report
    assert "End reason                  Flight ended before landing stop detected" in report


def test_cli_presentation_uses_exact_shared_flight_format(capsys):
    result = SimpleNamespace(report=[(1, 1, _attempt_analysis(rangefinder=True))])
    expected = format_landing_flight_result(result, 2)

    LandingAnalysis().present_result(result, 2)

    assert capsys.readouterr().out == f"\n{expected}\n"


def test_no_attempt_and_no_flight_reports_remain_distinct(tmp_path):
    no_attempts = format_landing_flight_result(SimpleNamespace(report=[]), 1)
    no_flights = format_landing_log_report(tmp_path / "empty.bin", (), 0)
    one_flight = format_landing_log_report(
        tmp_path / "one.bin", (SimpleNamespace(report=[]),), 1
    )

    assert "FLIGHT 1" in no_attempts
    assert "No landing attempts detected." in no_attempts
    assert "Loaded: 0 flight(s)\nNo flights detected." in no_flights
    assert "Flight results              0" in no_flights
    assert "No landing attempts detected." not in no_flights
    assert "Loaded: 1 flight(s)" in one_flight
    assert "No landing attempts detected." in one_flight
    assert "Flight results              1" in one_flight
