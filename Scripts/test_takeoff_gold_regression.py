"""Optional end-to-end TAKEOFF regression for the October 2026 Gold Log."""

import hashlib

import pytest
from core.log_reader import FlightReader
from core.takeoff_execution import TakeoffEntryContext, TakeoffTerminationReason
from core.takeoff_execution_detector import TakeoffExecutionDetector
from core.takeoff_performance import (
    RangefinderHeightResponseStatus,
    TakeoffPerformanceProcessor,
)
from test_support import require_log


GOLD_LOG = "Logs/log_1_2026-10-11-10-59-54.bin"
GOLD_LOG_SHA256 = (
    "9563146b8161f6ab38989f091b411be9716ac51b0b7a77156a80cba01892c887"
)
GOLD_TRIGGER_TIMES_US = (
    358_503_806,
    1_036_084_333,
    1_735_923_758,
    2_345_242_842,
    3_196_564_549,
    4_066_776_060,
    4_237_574_078,
    4_459_172_811,
)


@pytest.fixture(scope="module")
def gold_log_evidence():
    """Load and detect the exact optional Gold Log once for this module."""
    log_path = require_log(GOLD_LOG)
    with log_path.open("rb") as log_file:
        checksum = hashlib.file_digest(log_file, "sha256").hexdigest()
    assert checksum == GOLD_LOG_SHA256

    flight_log = FlightReader(log_path).read()
    executions = tuple(TakeoffExecutionDetector().detect(flight_log))
    return flight_log, executions


def test_gold_log_execution_ownership_and_completion(gold_log_evidence):
    """Retain all Gold Log Mode-13 ownership and completion boundaries."""
    flight_log, executions = gold_log_evidence
    mode_takeoffs = tuple(
        execution
        for execution in executions
        if execution.entry_context is TakeoffEntryContext.TAKEOFF_MODE
    )
    auto_takeoffs = tuple(
        execution
        for execution in executions
        if execution.entry_context is TakeoffEntryContext.AUTO_MISSION
    )
    triggered = tuple(
        execution
        for execution in mode_takeoffs
        if execution.launch_trigger is not None
    )
    already_airborne = tuple(
        execution
        for execution in mode_takeoffs
        if execution.already_airborne_entry is not None
        and execution.launch_trigger is None
    )
    ordinary_untriggered = tuple(
        execution
        for execution in mode_takeoffs
        if execution.launch_trigger is None
        and execution.already_airborne_entry is None
    )

    assert len(mode_takeoffs) == 10
    assert auto_takeoffs == ()
    assert len(triggered) == 8
    assert tuple(
        execution.launch_trigger.time_us for execution in triggered
    ) == GOLD_TRIGGER_TIMES_US
    assert len(already_airborne) == 1
    assert len(ordinary_untriggered) == 1

    untriggered = ordinary_untriggered[0]
    assert (untriggered.start_us, untriggered.end_us) == (
        288_484_173,
        290_164_092,
    )
    arm = flight_log.get("ARM")
    arm_before_entry = arm[arm["TimeUS"] <= untriggered.start_us].iloc[-1]
    assert int(arm_before_entry["ArmState"]) == 0

    completion_times = tuple(
        completion.time_us
        for execution in triggered
        if (completion := execution.takeoff_control_completion) is not None
    )
    censored = tuple(
        execution
        for execution in triggered
        if execution.takeoff_control_completion is None
    )
    assert completion_times == (1_042_883_762, 1_742_883_779)
    assert len(censored) == 6
    assert all(
        execution.termination_reason is TakeoffTerminationReason.MODE_EXIT
        for execution in triggered
    )


def test_gold_log_takeoff_7_negative_height_response(gold_log_evidence):
    """Preserve the signed RFNS and POS response of Gold Log TAKEOFF 7."""
    flight_log, executions = gold_log_evidence
    selected = tuple(
        execution
        for execution in executions
        if execution.launch_trigger is not None
        and execution.launch_trigger.time_us == 4_237_574_078
    )
    assert len(selected) == 1

    analysis = TakeoffPerformanceProcessor(flight_log, selected[0]).analyse()
    assert analysis is not None
    response = analysis.rangefinder_height_response

    assert response.status is RangefinderHeightResponseStatus.COMPLETE
    assert response.start_height_m == pytest.approx(1.71, abs=0.01)
    assert response.minimum_height_m == pytest.approx(1.47, abs=0.01)
    assert response.end_height_m == pytest.approx(1.47, abs=0.01)
    assert response.net_height_change_m == pytest.approx(-0.25, abs=0.01)
    assert analysis.altitude_delta_at_configured_minimum_airspeed_m == pytest.approx(
        -0.06,
        abs=0.01,
    )
