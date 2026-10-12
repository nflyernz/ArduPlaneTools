"""Contract-focused BDD for fixed-wing Plane 4.7.x AUTOTUNE evidence.

Synthetic records carry their original cross-message stream positions. These
checks deliberately do not reconstruct source order from message types.
"""

from pathlib import Path

import analyse
import analyses.autotune as presentation
import pandas as pd
import pytest
from core.autotune import (
    AutotuneAxis as Axis,
)
from core.autotune import (
    AutotuneExitOutcome as Exit,
)
from core.autotune import (
    AutotuneTerminationReason as Termination,
)
from core.autotune import (
    DemandState,
    SaveTriggerType,
)
from core.autotune_detector import AutotuneDetector
from core.config import Config
from core.flight_data import FlightLog
from core.flight_window import FlightWindow
from core.log_reader import FlightReader
from core.params import ParameterChange, ParameterHistory


def msg(time, text):
    return "MSG", {"TimeUS": time, "Message": text}


def atrp(time, axis=Axis.ROLL, state=0, action=0, **gains):
    return "ATRP", {
        "TimeUS": time,
        "Axis": int(axis),
        "State": state,
        "Action": action,
        "FF": gains.get("ff", 0.4),
        "P": gains.get("p", 0.2),
        "I": gains.get("i", 0.2),
        "D": gains.get("d", 0.01),
        "RMAX": gains.get("rmax", 75.0),
        "TAU": gains.get("tau", 0.5),
    }


def parm(time, name="RLL_RATE_P", value=0.2):
    return "PARM", {"TimeUS": time, "Name": name, "Value": value}


def mode(time, number):
    return "MODE", {"TimeUS": time, "ModeNum": number}


def ver(time, text="ArduPlane V4.7.0"):
    return "VER", {"TimeUS": time, "Maj": 4, "Min": 7, "Pat": 0, "FWS": text}


def command(time, kind="MAVC"):
    return kind, {"TimeUS": time, "Cmd": 212 if kind == "MAVC" else None, "CId": 212}


def _log(*events, mask=7, history=None, flights=(), end=None):
    """Retain exactly the supplied DataFlash order across message families."""
    messages = {}
    for order, (kind, fields) in enumerate(events):
        messages.setdefault(kind, []).append({**fields, "_SourceOrder": order})
    parameters = history or ParameterHistory(
        {
            "AUTOTUNE_AXES": mask,
            "AUTOTUNE_LEVEL": 6,
            "AUTOTUNE_OPTIONS": 0,
            "YAW_RATE_ENABLE": 0,
        }
    )
    last_time = max((fields.get("TimeUS", -1) for _, fields in events), default=None)
    return FlightLog(
        messages={kind: pd.DataFrame(rows) for kind, rows in messages.items()},
        parameter_history=parameters,
        flights=list(flights),
        metadata={
            "last_decoded_time_us": last_time if end is None else end[0],
            "last_decoded_source_order": len(events) - 1 if end is None else end[1],
        },
    )


def detect(*events, **kwargs):
    return AutotuneDetector().detect(_log(*events, **kwargs))


def only(*events, **kwargs):
    result = detect(*events, **kwargs)
    assert len(result.sessions) == 1
    return result.sessions[0]


def _codes(result):
    return [warning.code for warning in result.warnings]


def _save_case(*between, axis=Axis.ROLL, trigger_time=1_000_000, stop_time=1_200_000):
    """One milestone and nearby, trustworthy ATRP runtime evidence."""
    return detect(
        msg(900_000, "Started autotune"),
        atrp(trigger_time - 10_000, axis),
        msg(trigger_time, f"{axis.name.title()}: Finished"),
        *between,
        msg(stop_time, "Stopped autotune"),
    )


def _observations(result, axis=Axis.ROLL):
    return result.sessions[0].axes[axis].persistence.parameter_save_observations


def _requests(session, axis=Axis.ROLL):
    return session.axes[axis].persistence.save_requests


# Authoritative lifecycle; MODE, disarm, and flight detection are context only.


def test_normal_start_stop_has_exact_authoritative_boundaries():
    session = only(msg(100, "Started autotune"), msg(200, "Stopped autotune"))
    assert (session.start.time_us, session.end.time_us, session.duration_s) == (
        100,
        200,
        0.0001,
    )
    assert session.termination_reason is Termination.STOPPED


def test_two_independent_sessions_do_not_share_activity():
    result = detect(
        msg(100, "Started autotune"),
        atrp(150),
        msg(200, "Stopped autotune"),
        msg(300, "Started autotune"),
        atrp(350, Axis.PITCH),
        msg(400, "Stopped autotune"),
    )
    assert [(s.start.time_us, s.end.time_us) for s in result.sessions] == [
        (100, 200),
        (300, 400),
    ]
    assert [s.active_axes for s in result.sessions] == [(Axis.ROLL,), (Axis.PITCH,)]


def test_repeated_start_ends_prior_session_and_opens_fresh_session_at_same_event():
    result = detect(
        msg(100, "Started autotune"),
        atrp(150),
        msg(200, "Started autotune"),
        atrp(250, Axis.PITCH),
        msg(300, "Stopped autotune"),
    )
    first, second = result.sessions
    assert first.termination_reason is Termination.RESTARTED
    assert first.end == second.start
    assert first.active_axes == (Axis.ROLL,)
    assert second.active_axes == (Axis.PITCH,)
    assert second.termination_reason is Termination.STOPPED


def test_open_session_ends_at_decoded_log_end_with_no_normal_stop():
    result = detect(
        msg(100, "Started autotune"),
        atrp(200),
        ("UNRETAINED", {"TimeUS": 500}),
        ("FMT", {}),
        end=(500, 3),
    )
    session = result.sessions[0]
    assert session.end.time_us == 500
    assert session.end.source_order == 3
    assert session.termination_reason is Termination.LOG_END
    assert session.axes[Axis.ROLL].persistence.exit_outcome is Exit.UNKNOWN
    assert "NORMAL_STOP_NOT_OBSERVED" in _codes(result)


def test_unmatched_stop_is_warning_without_synthetic_session():
    result = detect(msg(100, "Stopped autotune"))
    assert result.sessions == []
    assert _codes(result) == ["ORPHAN_STOP"]


@pytest.mark.parametrize(
    "context",
    [
        ("ARM", {"TimeUS": 150, "ArmState": 0}),
        mode(150, 0),
    ],
    ids=["disarm", "mode-exit"],
)
def test_context_events_cannot_end_session(context):
    session = only(
        msg(100, "Started autotune"), context, atrp(250), msg(300, "Stopped autotune")
    )
    assert session.end.time_us == 300
    assert session.axes[Axis.ROLL].atrp_count == 1


def test_flight_window_end_cannot_end_session():
    session = only(
        msg(100, "Started autotune"),
        atrp(250),
        msg(300, "Stopped autotune"),
        flights=(FlightWindow(120, 200),),
    )
    assert session.end.time_us == 300
    assert session.flight_relations[0].extends_beyond_flight


# Equal-TimeUS ownership follows the original DataFlash stream order.


@pytest.mark.parametrize("at_start,owned", [(True, False), (False, True)])
def test_atrp_equal_time_to_start_obeys_source_order(at_start, owned):
    sample = atrp(100)
    start = msg(100, "Started autotune")
    records = (sample, start) if at_start else (start, sample)
    result = detect(*records, msg(200, "Stopped autotune"))
    assert result.sessions[0].axes[Axis.ROLL].atrp_count == int(owned)
    assert ("ORPHAN_ATRP" in _codes(result)) is not owned


@pytest.mark.parametrize("before_stop,owned", [(True, True), (False, False)])
def test_atrp_equal_time_to_stop_obeys_source_order(before_stop, owned):
    sample = atrp(200)
    stop = msg(200, "Stopped autotune")
    records = (sample, stop) if before_stop else (stop, sample)
    result = detect(msg(100, "Started autotune"), *records)
    assert result.sessions[0].axes[Axis.ROLL].atrp_count == int(owned)
    assert ("ORPHAN_ATRP" in _codes(result)) is not owned


def test_equal_time_parm_before_finished_is_not_attributed():
    result = detect(
        msg(900_000, "Started autotune"),
        atrp(990_000),
        parm(1_000_000),
        msg(1_000_000, "Roll: Finished"),
        msg(1_200_000, "Stopped autotune"),
    )
    assert _observations(result) == []


def test_equal_time_parm_after_finished_is_attributed_with_matching_runtime():
    result = _save_case(parm(1_000_000))
    observations = _observations(result)
    assert len(observations) == 1
    assert observations[0].trigger.trigger_type is SaveTriggerType.FINISHED_MILESTONE
    assert (
        observations[0].position.source_order
        > observations[0].trigger.position.source_order
    )


# Reader order and exact decoded evidence end, including unretained records.


class _Message:
    def __init__(self, kind, **fields):
        self.kind, self.fields = kind, fields

    def get_type(self):
        return self.kind

    def to_dict(self):
        return {"mavpackettype": self.kind, **self.fields}


class _Connection:
    def __init__(self, records):
        self.records = iter(records)

    def recv_match(self):
        return next(self.records, None)


def test_reader_keeps_order_through_unretained_and_bad_data(monkeypatch):
    records = [
        _Message("VER", TimeUS=10, Maj=4, Min=7, Pat=0, FWS="ArduPlane V4.7.0"),
        _Message("UNRETAINED", TimeUS=20),
        _Message("BAD_DATA", TimeUS=25),
        _Message("MSG", TimeUS=30, Message="Started autotune"),
        _Message("ATRP", TimeUS=40, Axis=0),
        _Message("FMT"),
    ]
    monkeypatch.setattr(
        "core.log_reader.mavutil.mavlink_connection", lambda _path: _Connection(records)
    )
    messages, _, metadata = FlightReader(
        "synthetic.bin", Config("Config/autotune.yaml")
    )._read_messages()
    assert int(messages["VER"].iloc[0]["_SourceOrder"]) == 0
    assert int(messages["MSG"].iloc[0]["_SourceOrder"]) == 2
    assert int(messages["ATRP"].iloc[0]["_SourceOrder"]) == 3
    assert int(messages["MSG"].iloc[0]["TimeUS"]) == 30
    assert messages.get("BAD_DATA") is None
    assert metadata == {"last_decoded_source_order": 4, "last_decoded_time_us": 40}


def test_unclosed_session_uses_reader_metadata_not_latest_retained_message(monkeypatch):
    records = [
        _Message("VER", TimeUS=10, Maj=4, Min=7, Pat=0, FWS="ArduPlane V4.7.0"),
        _Message("MSG", TimeUS=100, Message="Started autotune"),
        _Message("UNRETAINED", TimeUS=500),
        _Message("FMT"),
    ]
    monkeypatch.setattr(
        "core.log_reader.mavutil.mavlink_connection", lambda _path: _Connection(records)
    )
    messages, history, metadata = FlightReader(
        "synthetic.bin", Config("Config/autotune.yaml")
    )._read_messages()
    log = FlightLog(messages=messages, parameter_history=history, metadata=metadata)
    session = AutotuneDetector().detect(log).sessions[0]
    assert session.termination_reason is Termination.LOG_END
    assert (session.end.time_us, session.end.source_order) == (500, 3)


# Historical configuration, explicit selection, and ATRP activity are separate.


@pytest.mark.parametrize(
    "mask,expected",
    [
        (1, (Axis.ROLL,)),
        (2, (Axis.PITCH,)),
        (4, (Axis.YAW,)),
        (3, (Axis.ROLL, Axis.PITCH)),
        (7, tuple(Axis)),
    ],
)
def test_configured_axis_masks(mask, expected):
    session = only(
        msg(100, "Started autotune"), msg(200, "Stopped autotune"), mask=mask
    )
    assert session.configured_axes == expected
    assert session.selected_axes is None
    assert session.active_axes == ()


def test_configuration_is_timestamp_aware_across_sessions():
    history = ParameterHistory(
        {"AUTOTUNE_AXES": 1, "YAW_RATE_ENABLE": 0},
        {"AUTOTUNE_AXES": (ParameterChange(250, 2),)},
    )
    result = detect(
        msg(100, "Started autotune"),
        msg(200, "Stopped autotune"),
        msg(300, "Started autotune"),
        msg(400, "Stopped autotune"),
        history=history,
    )
    assert [s.configured_axes for s in result.sessions] == [(Axis.ROLL,), (Axis.PITCH,)]


@pytest.mark.parametrize(
    "mask,selection,activity,configured,selected,active",
    [
        (1, "roll", Axis.ROLL, (Axis.ROLL,), (Axis.ROLL,), (Axis.ROLL,)),
        (2, "pitch", Axis.PITCH, (Axis.PITCH,), (Axis.PITCH,), (Axis.PITCH,)),
        (4, "yaw", Axis.YAW, (Axis.YAW,), (Axis.YAW,), (Axis.YAW,)),
        (
            3,
            "roll pitch",
            Axis.ROLL,
            (Axis.ROLL, Axis.PITCH),
            (Axis.ROLL, Axis.PITCH),
            (Axis.ROLL,),
        ),
        (7, "roll pitch yaw", Axis.PITCH, tuple(Axis), tuple(Axis), (Axis.PITCH,)),
        (1, "pitch", Axis.PITCH, (Axis.ROLL,), (Axis.PITCH,), (Axis.PITCH,)),
        (2, "roll", Axis.PITCH, (Axis.PITCH,), (Axis.ROLL,), (Axis.PITCH,)),
    ],
)
def test_configured_selected_and_active_are_independent(
    mask, selection, activity, configured, selected, active
):
    session = only(
        msg(100, "Started autotune"),
        msg(110, "Autotuning " + selection),
        atrp(150, activity),
        msg(200, "Stopped autotune"),
        mask=mask,
    )
    assert (session.configured_axes, session.selected_axes, session.active_axes) == (
        configured,
        selected,
        active,
    )


def test_selected_inactive_yaw_and_disabled_yaw_rate_are_distinct_evidence():
    session = only(
        msg(100, "Started autotune"),
        msg(110, "Autotuning roll pitch yaw"),
        atrp(150, Axis.ROLL),
        msg(200, "Stopped autotune"),
    )
    assert Axis.YAW in session.selected_axes
    assert session.configuration["YAW_RATE_ENABLE"] == 0
    assert not session.axes[Axis.YAW].active


# Demand periods derive from observed ATRP state runs, not guessed gaps.


@pytest.mark.parametrize(
    "states,expected",
    [
        ([0, 0, 0], []),
        ([0, 1, 1, 0], [(DemandState.DEMAND_POS, 1, 3, True)]),
        ([0, 2, 2, 0], [(DemandState.DEMAND_NEG, 1, 3, True)]),
        (
            [1, 2, 0],
            [
                (DemandState.DEMAND_POS, 0, 1, True),
                (DemandState.DEMAND_NEG, 1, 2, True),
            ],
        ),
        (
            [0, 1, 0, 2, 0, 1, 0],
            [
                (DemandState.DEMAND_POS, 1, 2, True),
                (DemandState.DEMAND_NEG, 3, 4, True),
                (DemandState.DEMAND_POS, 5, 6, True),
            ],
        ),
        ([0, 1, 1], [(DemandState.DEMAND_POS, 1, 2, False)]),
    ],
)
def test_demand_periods_follow_observed_state_runs(states, expected):
    samples = [atrp(110 + 10 * i, state=state) for i, state in enumerate(states)]
    axis = only(
        msg(100, "Started autotune"), *samples, msg(300, "Stopped autotune")
    ).axes[Axis.ROLL]
    actual = [
        (
            p.state,
            (p.start.time_us - 110) // 10,
            (p.end.time_us - 110) // 10,
            p.end_transition_observed,
        )
        for p in axis.demand_periods
    ]
    assert actual == expected
    assert axis.positive_demand_periods == sum(
        p[0] is DemandState.DEMAND_POS for p in expected
    )
    assert axis.negative_demand_periods == sum(
        p[0] is DemandState.DEMAND_NEG for p in expected
    )


@pytest.mark.parametrize("duration", [1_000_000, 3_600_000])
def test_short_session_can_have_activity_without_demand_or_exit_certainty(duration):
    axis = only(
        msg(100, "Started autotune"),
        atrp(100_000),
        atrp(200_000),
        msg(100 + duration, "Stopped autotune"),
    ).axes[Axis.ROLL]
    assert axis.active
    assert axis.demand_periods == []
    assert axis.persistence.exit_outcome is Exit.UNKNOWN


def test_partial_d_limit_short_session_stays_unknown():
    session = only(
        msg(100, "Started autotune"),
        atrp(200, state=1),
        msg(300, "RollD: 0.0074"),
        atrp(400, state=0),
        msg(500, "Stopped autotune"),
    )
    roll = session.axes[Axis.ROLL]
    assert roll.active and len(roll.demand_periods) == 1
    assert [(g.kind, g.value) for g in roll.gain_limit_events] == [("D", 0.0074)]
    assert roll.completion_events == []
    assert roll.persistence.exit_outcome is Exit.UNKNOWN


# Action is latched; the first value is an observation baseline.


@pytest.mark.parametrize(
    "actions,expected",
    [
        ([0], []),
        ([3, 3, 3], []),
        ([0, 0, 6], [(0, 6)]),
        ([0, 6, 6, 9, 3], [(0, 6), (6, 9), (9, 3)]),
    ],
)
def test_action_baseline_and_only_actual_transitions(actions, expected):
    samples = [atrp(110 + 10 * i, action=action) for i, action in enumerate(actions)]
    axis = only(
        msg(100, "Started autotune"), *samples, msg(300, "Stopped autotune")
    ).axes[Axis.ROLL]
    assert axis.action_baseline == actions[0]
    assert [(t.previous, t.current) for t in axis.action_transitions] == expected
    assert [t.position.time_us for t in axis.action_transitions] == [
        110 + 10 * i for i in range(1, len(actions)) if actions[i] != actions[i - 1]
    ]
    assert all(t.position.source_order is not None for t in axis.action_transitions)


def test_stale_nonzero_action_on_reentry_is_baseline_not_fresh_event():
    result = detect(
        msg(100, "Started autotune"),
        atrp(150, action=9),
        msg(200, "Stopped autotune"),
        msg(300, "Started autotune"),
        atrp(350, action=9),
        atrp(360, action=9),
        msg(400, "Stopped autotune"),
    )
    second = result.sessions[1].axes[Axis.ROLL]
    assert second.action_baseline == 9
    assert second.action_transitions == []


# Explicit P/D limit events and completion milestones are chronological evidence.


@pytest.mark.parametrize(
    "texts,expected",
    [
        ([], []),
        (["RollP: 0.2"], [("P", 0.2)]),
        (["RollD: 0.01"], [("D", 0.01)]),
        (["RollP: 0.2", "RollD: 0.01"], [("P", 0.2), ("D", 0.01)]),
        (["RollD: 0.01", "RollP: 0.2"], [("D", 0.01), ("P", 0.2)]),
        (["RollP: 0.2", "RollP: 0.15"], [("P", 0.2), ("P", 0.15)]),
        (["RollD: 0.01", "RollD: 0.008"], [("D", 0.01), ("D", 0.008)]),
    ],
)
def test_every_gain_limit_event_is_retained_in_order(texts, expected):
    records = [msg(110 + i * 10, text) for i, text in enumerate(texts)]
    axis = only(
        msg(100, "Started autotune"), *records, msg(300, "Stopped autotune")
    ).axes[Axis.ROLL]
    assert [(g.kind, g.value) for g in axis.gain_limit_events] == expected
    assert [g.position.time_us for g in axis.gain_limit_events] == [
        110 + 10 * i for i in range(len(texts))
    ]


def test_gain_limits_on_different_axes_remain_separate():
    session = only(
        msg(100, "Started autotune"),
        msg(110, "RollD: 0.01"),
        msg(120, "PitchP: 0.2"),
        msg(130, "YawD: 0.003"),
        msg(200, "Stopped autotune"),
    )
    assert [
        [event.axis for event in session.axes[a].gain_limit_events] for a in Axis
    ] == [[Axis.ROLL], [Axis.PITCH], [Axis.YAW]]


def test_repeated_completion_retains_intervening_revision_and_later_activity():
    session = only(
        msg(100, "Started autotune"),
        atrp(110, p=0.2),
        msg(120, "RollD: 0.01"),
        msg(130, "RollP: 0.2"),
        msg(140, "Roll: Finished"),
        atrp(150, p=0.2),
        msg(160, "RollP: 0.15"),
        atrp(170, p=0.15),
        msg(180, "Roll: Finished"),
        atrp(190, p=0.15),
        msg(200, "Stopped autotune"),
    )
    roll = session.axes[Axis.ROLL]
    assert [e.position.time_us for e in roll.completion_events] == [140, 180]
    assert [e.value for e in roll.gain_limit_events if e.kind == "P"] == [0.2, 0.15]
    assert (
        roll.completion_events[0].position.key
        < roll.gain_limit_events[-1].position.key
        < roll.completion_events[1].position.key
    )
    assert roll.atrp_count == 4
    assert roll.final_observed_runtime_gains.p == 0.15
    assert (
        len(
            [
                r
                for r in _requests(session)
                if r.trigger_type is SaveTriggerType.FINISHED_MILESTONE
            ]
        )
        == 2
    )


def test_completion_is_axis_specific_without_global_verdict():
    session = only(
        msg(100, "Started autotune"),
        msg(110, "Pitch: Finished"),
        msg(120, "Yaw: Finished"),
        msg(200, "Stopped autotune"),
    )
    assert [len(session.axes[a].completion_events) for a in Axis] == [0, 1, 1]
    assert [len(session.axes[a].persistence.save_requests) for a in Axis] == [0, 2, 2]


def test_no_finished_does_not_create_milestone_request():
    session = only(
        msg(100, "Started autotune"), atrp(150), msg(200, "Stopped autotune")
    )
    assert session.axes[Axis.ROLL].completion_events == []
    assert _requests(session) == []


def test_entry_and_last_observed_runtime_values_are_distinct_from_storage():
    session = only(
        msg(100, "Started autotune"),
        atrp(110, ff=0.4, p=0.2),
        msg(120, "Roll: Finished"),
        atrp(130, ff=0.5, p=0.3),
        msg(200, "Stopped autotune"),
    )
    roll = session.axes[Axis.ROLL]
    assert roll.entry_runtime_gains.position.time_us == 110
    assert roll.entry_runtime_gains.values[:2] == (0.4, 0.2)
    assert roll.final_observed_runtime_gains.position.time_us == 130
    assert roll.final_observed_runtime_gains.values[:2] == (0.5, 0.3)
    assert roll.persistence.physical_persistence_verified is False
    assert roll.persistence.parameter_save_observations == []


# Exit semantics: positive P/D state can request save before Finished.


@pytest.mark.parametrize(
    "events,outcome,request_count",
    [
        ([msg(120, "RollP: 0.2"), msg(130, "RollD: 0.01")], Exit.SAVE_REQUESTED, 1),
        ([msg(120, "RollD: 0.01"), msg(130, "RollP: 0.2")], Exit.SAVE_REQUESTED, 1),
        ([msg(120, "RollP: 0.2")], Exit.UNKNOWN, 0),
        ([msg(120, "RollD: 0.01")], Exit.UNKNOWN, 0),
        ([], Exit.UNKNOWN, 0),
    ],
)
def test_normal_stop_exit_evidence(events, outcome, request_count):
    session = only(
        msg(100, "Started autotune"), atrp(110), *events, msg(200, "Stopped autotune")
    )
    roll = session.axes[Axis.ROLL]
    assert roll.persistence.exit_outcome is outcome
    assert len(_requests(session)) == request_count
    assert roll.persistence.parameter_save_observations == []


def test_demand_and_raise_d_without_limits_can_infer_restore():
    session = only(
        msg(100, "Started autotune"),
        atrp(110, state=1, action=0),
        atrp(120, state=0, action=6),
        msg(200, "Stopped autotune"),
    )
    assert session.axes[Axis.ROLL].persistence.exit_outcome is Exit.RESTORE_INFERRED
    assert _requests(session) == []


def test_finished_requests_save_without_raw_parm():
    session = only(
        msg(100, "Started autotune"),
        atrp(110),
        msg(120, "Roll: Finished"),
        msg(200, "Stopped autotune"),
    )
    assert [r.trigger_type for r in _requests(session)] == [
        SaveTriggerType.FINISHED_MILESTONE,
        SaveTriggerType.SESSION_EXIT,
    ]
    assert session.axes[Axis.ROLL].persistence.parameter_save_observations == []


# PARM attribution: 40 ms is a conservative APT guard, not firmware timing.


@pytest.mark.parametrize(
    "offset,correlated", [(39_999, True), (40_000, True), (40_001, False)]
)
def test_parm_guard_boundary(offset, correlated):
    result = _save_case(parm(1_000_000 + offset))
    assert bool(_observations(result)) is correlated


def test_next_same_axis_atrp_ends_prior_milestone_neighborhood():
    result = _save_case(atrp(1_010_000), parm(1_010_001))
    assert _observations(result) == []


@pytest.mark.parametrize(
    "name,value",
    [
        ("RLL_RATE_FF", 0.4),
        ("RLL_RATE_P", 0.2),
        ("RLL_RATE_I", 0.2),
        ("RLL_RATE_D", 0.01),
        ("RLL_RATE_P", 0.2000001),
        ("RLL_RATE_D", 0.010000009),
    ],
)
def test_comparable_runtime_values_can_correlate(name, value):
    observation = _observations(_save_case(parm(1_000_001, name, value)))[0]
    assert observation.name == name
    assert observation.agreeing_runtime.time_us == 990_000


def test_near_zero_value_uses_absolute_float32_tolerance():
    result = detect(
        msg(900_000, "Started autotune"),
        atrp(990_000, d=0.0),
        msg(1_000_000, "Roll: Finished"),
        parm(1_000_001, "RLL_RATE_D", 8e-9),
        msg(1_200_000, "Stopped autotune"),
    )
    assert len(_observations(result)) == 1


def test_post_trigger_runtime_can_correlate_before_next_atrp_record():
    result = detect(
        msg(900_000, "Started autotune"),
        atrp(990_000, p=0.2),
        msg(1_000_000, "Roll: Finished"),
        parm(1_000_001, "RLL_RATE_P", 0.25),
        atrp(1_000_010, p=0.25),
        msg(1_200_000, "Stopped autotune"),
    )
    observation = _observations(result)[0]
    assert observation.agreeing_runtime.time_us == 1_000_010


@pytest.mark.parametrize(
    "name,value",
    [
        ("RLL_RATE_P", 0.25),
        ("RLL_RATE_FF", 0.5),
        ("RLL_RATE_IMAX", 1.0),
        ("RLL_RATE_FLTD", 10.0),
    ],
)
def test_conflicting_or_unobservable_value_is_not_attributed(name, value):
    assert _observations(_save_case(parm(1_000_001, name, value))) == []


def test_conflicting_controlled_value_stops_rest_of_burst():
    result = _save_case(
        parm(1_000_001, "RLL_RATE_P", 0.5), parm(1_000_002, "RLL_RATE_D", 0.01)
    )
    assert _observations(result) == []


@pytest.mark.parametrize(
    "barrier",
    [
        msg(1_000_001, "Started autotune"),
        msg(1_000_001, "RollD: 0.01"),
        command(1_000_001, "MAVC"),
        command(1_000_001, "MISE"),
        parm(1_000_001, "BATT_CAPACITY", 3000),
    ],
    ids=["new-start", "gain-limit", "MAVC", "MISE", "unrelated-PARM"],
)
def test_barrier_prevents_prior_milestone_claim(barrier):
    result = _save_case(barrier, parm(1_000_002))
    assert _observations(result) == []


def test_stop_barrier_moves_attribution_to_exit_trigger():
    result = detect(
        msg(900_000, "Started autotune"),
        atrp(990_000),
        msg(1_000_000, "Roll: Finished"),
        msg(1_000_001, "Stopped autotune"),
        parm(1_000_002),
    )
    observations = _observations(result)
    assert len(observations) == 1
    assert observations[0].trigger.trigger_type is SaveTriggerType.SESSION_EXIT


def test_new_finished_barrier_moves_attribution_to_new_milestone():
    result = _save_case(msg(1_000_001, "Roll: Finished"), parm(1_000_002))
    observations = _observations(result)
    assert len(observations) == 1
    assert observations[0].trigger.position.time_us == 1_000_001


@pytest.mark.parametrize(
    "axis,other_parameter", [(Axis.ROLL, "PTCH_RATE_P"), (Axis.PITCH, "RLL_RATE_P")]
)
def test_milestone_cannot_claim_other_axis_write(axis, other_parameter):
    result = _save_case(parm(1_000_001, other_parameter, 0.2), axis=axis)
    assert _observations(result, axis) == []


def test_simultaneous_exit_saves_can_claim_each_axis_once():
    result = detect(
        msg(900_000, "Started autotune"),
        msg(950_000, "RollD: 0.01"),
        msg(950_001, "RollP: 0.2"),
        msg(950_002, "PitchD: 0.01"),
        msg(950_003, "PitchP: 0.2"),
        atrp(990_000, Axis.ROLL),
        atrp(990_001, Axis.PITCH),
        msg(1_000_000, "Stopped autotune"),
        parm(1_000_001, "RLL_RATE_P", 0.2),
        parm(1_000_002, "PTCH_RATE_P", 0.2),
        parm(1_000_003, "YAW_RATE_P", 0.2),
    )
    session = result.sessions[0]
    assert [
        session.axes[a].persistence.exit_outcome for a in (Axis.ROLL, Axis.PITCH)
    ] == [Exit.SAVE_REQUESTED, Exit.SAVE_REQUESTED]
    roll, pitch, yaw = (_observations(result, a) for a in Axis)
    assert [p.name for p in roll] == ["RLL_RATE_P"]
    assert [p.name for p in pitch] == ["PTCH_RATE_P"]
    assert yaw == []
    assert {p.position.key for p in roll + pitch} == {
        roll[0].position.key,
        pitch[0].position.key,
    }
    assert all(
        p.trigger.trigger_type is SaveTriggerType.SESSION_EXIT for p in roll + pitch
    )


def test_raw_parm_never_turns_into_a_firmware_save_request():
    session = only(
        msg(100, "Started autotune"),
        atrp(110),
        parm(120, "RLL_RATE_P", 0.2),
        msg(200, "Stopped autotune"),
    )
    assert session.axes[Axis.ROLL].persistence.save_requests == []
    assert session.axes[Axis.ROLL].persistence.parameter_save_observations == []


# Continuity requires all reported runtime gain fields for each axis.


def test_continuity_is_axis_specific_and_requires_exact_match():
    result = detect(
        msg(100, "Started autotune"),
        atrp(110, Axis.ROLL, p=0.2),
        atrp(120, Axis.PITCH, p=0.3),
        msg(200, "Stopped autotune"),
        msg(300, "Started autotune"),
        atrp(310, Axis.ROLL, p=0.2),
        atrp(320, Axis.PITCH, p=0.4),
        msg(400, "Stopped autotune"),
    )
    second = result.sessions[1]
    assert second.axes[Axis.ROLL].persistence.runtime_continuity_from_session == 1
    assert second.axes[Axis.PITCH].persistence.runtime_continuity_from_session is None
    assert second.axes[Axis.ROLL].persistence.physical_persistence_verified is False


@pytest.mark.parametrize("first,second", [(False, True), (True, False)])
def test_missing_runtime_side_cannot_establish_continuity(first, second):
    result = detect(
        msg(100, "Started autotune"),
        *([atrp(150)] if first else []),
        msg(200, "Stopped autotune"),
        msg(300, "Started autotune"),
        *([atrp(350)] if second else []),
        msg(400, "Stopped autotune"),
    )
    assert (
        result.sessions[1].axes[Axis.ROLL].persistence.runtime_continuity_from_session
        is None
    )


# Orphans remain evidence warnings; no authoritative session is invented.


def test_orphan_axis_evidence_is_retained_without_session():
    result = detect(
        atrp(100),
        msg(110, "RollD: 0.01"),
        msg(120, "Roll: Finished"),
        msg(130, "Stopped autotune"),
    )
    assert result.sessions == []
    assert _codes(result) == [
        "ORPHAN_ATRP",
        "ORPHAN_MESSAGE",
        "ORPHAN_MESSAGE",
        "ORPHAN_STOP",
    ]
    assert [w.record["Message"] for w in result.warnings[1:3]] == [
        "RollD: 0.01",
        "Roll: Finished",
    ]


# FlightWindows are context and never redefine AUTOTUNE lifetime.


@pytest.mark.parametrize(
    "windows,expected",
    [
        ((FlightWindow(50, 250),), [(1, False, False)]),
        ((FlightWindow(50, 150),), [(1, False, True)]),
        ((FlightWindow(150, 250),), [(1, True, False)]),
        ((), []),
    ],
)
def test_flight_association_is_context_only(windows, expected):
    session = only(
        msg(100, "Started autotune"),
        atrp(160),
        msg(200, "Stopped autotune"),
        flights=windows,
    )
    assert (session.start.time_us, session.end.time_us) == (100, 200)
    assert [
        (r.flight_number, r.starts_before_flight, r.extends_beyond_flight)
        for r in session.flight_relations
    ] == expected


# Narrow presentation checks; no full-output snapshots.


def test_menu_option_five_dispatches_autotune(monkeypatch):
    called = []
    monkeypatch.setattr(
        presentation.AutotuneAnalysisPresentation,
        "run",
        lambda self: called.append(True),
    )
    answers = iter(("5", "0"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    analyse.menu()
    assert called == [True]


def test_presentation_uses_single_log_shared_selector(monkeypatch, capsys):
    selected = Path("Logs/synthetic.bin")
    received = []
    log = _log(
        ver(90),
        msg(100, "Started autotune"),
        msg(110, "Autotuning roll pitch yaw"),
        atrp(120),
        msg(130, "Roll: Finished"),
        msg(140, "Roll: Finished"),
        msg(200, "Stopped autotune"),
        flights=(FlightWindow(50, 250),),
    )
    monkeypatch.setattr(presentation, "select_log_input", lambda: [selected])

    class Reader:
        def __init__(self, path, config=None):
            received.append((path, config))

        def read(self):
            return log

    monkeypatch.setattr(presentation, "FlightReader", Reader)
    presentation.AutotuneAnalysisPresentation().run()
    output = capsys.readouterr().out
    assert received[0][0] == selected
    assert "Log: Logs/synthetic.bin" in output
    assert "Firmware: ArduPlane V4.7.0" in output
    assert "Flight association: Flight 1" in output
    assert "selected; YAW_RATE_ENABLE=0" in output
    assert "Mode observed at start:" not in output
    assert output.count("Completion milestone observed") == 2


def test_report_labels_missing_firmware_evidence():
    """Synthetic logs without VER retain an explicit unavailable distinction."""
    report = presentation.format_autotune_report(
        detect(),
        Path("Logs/no-ver.bin"),
    )

    assert "Log: Logs/no-ver.bin" in report
    assert "Firmware: Evidence unavailable" in report
