"""Regression tests for TAKEOFF telemetry-row caching semantics."""

import math

import pandas as pd
import pytest
from core.params import ParameterChange
from core.takeoff_performance import (
    ConfiguredMinimumAirspeedStatus,
    RangefinderHeightResponseStatus,
    TakeoffPerformanceProcessor,
    TakeoffTelemetryRowCache,
    format_takeoff_performance_report,
)
from test_takeoff_performance import (
    COMPLETION_US,
    TARGET_US,
    TRIGGER_US,
    UNSUPPRESSED_US,
    _execution,
    _flight_log,
    _history,
)


def test_shared_cache_prepares_each_requested_message_once(monkeypatch):
    """Processors for one log share one preparation per message type."""
    flight_log = _flight_log(
        ctun=((TRIGGER_US, 0.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),),
        gps=((TRIGGER_US, 0, 3, 4.0, 0),),
    )
    cache = TakeoffTelemetryRowCache(flight_log)
    processors = (
        TakeoffPerformanceProcessor(flight_log, _execution(), cache),
        TakeoffPerformanceProcessor(flight_log, _execution(), cache),
    )
    original_iterrows = pd.DataFrame.iterrows
    prepared_dataframes = []

    def counted_iterrows(dataframe):
        prepared_dataframes.append(dataframe)
        return original_iterrows(dataframe)

    monkeypatch.setattr(pd.DataFrame, "iterrows", counted_iterrows)

    first_ctun = processors[0]._rows("CTUN")
    assert processors[1]._rows("CTUN") is first_ctun
    first_gps = processors[1]._rows("GPS")
    assert processors[0]._rows("GPS") is first_gps

    assert prepared_dataframes == [flight_log.get("CTUN"), flight_log.get("GPS")]


def test_standalone_processors_keep_independent_cache_scope():
    """Direct processor construction does not leak cached rows across instances."""
    flight_log = _flight_log()
    first = TakeoffPerformanceProcessor(flight_log, _execution())
    second = TakeoffPerformanceProcessor(flight_log, _execution())

    assert first._row_cache is not second._row_cache
    assert first._row_cache.flight_log is flight_log
    assert second._row_cache.flight_log is flight_log

    other_log = _flight_log()
    with pytest.raises(ValueError, match="different flight log"):
        TakeoffPerformanceProcessor(
            other_log,
            _execution(),
            TakeoffTelemetryRowCache(flight_log),
        )


def test_cached_rows_preserve_validation_and_stable_source_order():
    """Invalid times are rejected and equal times retain DataFrame source order."""
    flight_log = _flight_log(
        ctun=(
            (3_000_000, 30.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),
            (2_000_000, 10.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),
            (2_000_000, 20.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),
            (2_500_000.5, 40.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),
            (math.nan, 50.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),
            ("invalid", 60.0, 0.0, 0.0, 0.0, 8.0, 1, 0.0),
        )
    )

    rows = TakeoffTelemetryRowCache(flight_log).rows("CTUN")

    assert [row.time_us for row in rows] == [2_000_000, 2_000_000, 3_000_000]
    assert [row.source_order for row in rows] == [1, 2, 0]
    assert [row.row["NavPitch"] for row in rows] == [10.0, 20.0, 30.0]


def test_shared_cache_preserves_boundaries_parameters_ties_and_report():
    """Shared rows retain causal, interval, tie, and presentation semantics."""
    history = _history(
        {
            "AIRSPEED_MIN": 12.0,
            "TKOFF_ROTATE_SPD": 0.0,
            "RNGFND_LND_ORNT": 25.0,
        },
        {"AIRSPEED_MIN": (ParameterChange(TARGET_US, 10.0),)},
    )
    flight_log = _flight_log(
        ctun=(
            (COMPLETION_US, 0.0, 0.0, 0.0, 0.0, 99.0, 1, 99.0),
            (UNSUPPRESSED_US, 0.0, 0.0, 0.0, 0.0, 10.5, 1, 20.0),
            (3_500_000, 0.0, 0.0, 0.0, 0.0, 11.0, 1, 90.0),
            (TRIGGER_US, 0.0, 0.0, 0.0, 0.0, 1.0, 1, 1.0),
            (TARGET_US, 0.0, 0.0, 0.0, 0.0, 11.5, 1, 90.0),
        ),
        bat=(
            (UNSUPPRESSED_US - 1, 0, 50.0),
            (UNSUPPRESSED_US, 0, 5.0),
            (TARGET_US, 0, 30.0),
            (TARGET_US + 1, 0, 100.0),
        ),
        pos=((TRIGGER_US, 10.0), (UNSUPPRESSED_US, 9.5)),
        rfns=(
            (UNSUPPRESSED_US, 1.5, 1),
            (3_500_000, 1.5, 1),
            (TARGET_US, 2.0, 1),
        ),
        parameter_history=history,
    )
    execution = _execution()

    standalone = TakeoffPerformanceProcessor(flight_log, execution).analyse()
    shared = TakeoffPerformanceProcessor(
        flight_log,
        execution,
        TakeoffTelemetryRowCache(flight_log),
    ).analyse()

    assert shared == standalone
    assert shared is not None
    assert standalone is not None
    assert format_takeoff_performance_report(
        shared, 1
    ) == format_takeoff_performance_report(standalone, 1)

    # Control aggregates remain open at trigger/completion.
    assert shared.airspeed_envelope is not None
    assert shared.airspeed_envelope.minimum.value_m_s == 10.5
    assert shared.airspeed_envelope.maximum.value_m_s == 11.5

    # AIRSPEED_MIN changes exactly at this sample and applies to that sample.
    observed = shared.first_observed_configured_minimum_airspeed
    assert observed.status is ConfiguredMinimumAirspeedStatus.OBSERVED
    assert observed.observation_time_us == TARGET_US
    assert observed.configured_minimum_m_s == 10.0

    # Propulsion evidence remains inclusive at release and the airspeed sample.
    propulsion = shared.propulsion_to_configured_minimum_airspeed
    assert propulsion is not None
    assert propulsion.start_us == UNSUPPRESSED_US
    assert propulsion.end_us == TARGET_US
    assert propulsion.peak_battery_current_a is not None
    assert propulsion.peak_battery_current_a.value == 30.0

    # Equal RFNS minima continue to retain the earliest eligible source sample.
    rangefinder = shared.rangefinder_height_response
    assert rangefinder.status is RangefinderHeightResponseStatus.COMPLETE
    assert rangefinder.minimum_sample_time_us == UNSUPPRESSED_US
