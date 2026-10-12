"""Focused tests for TAKEOFF analysis menu integration and presentation."""

from pathlib import Path

import analyse
import analyses.takeoff as takeoff_module
from analyses.takeoff import TakeoffAnalysisPresentation
from core.flight_data import FlightLog
from core.takeoff_execution import (
    TakeoffEntryContext,
    TakeoffExecution,
    TakeoffExecutionEvent,
    TakeoffExecutionEventType,
    TakeoffTerminationReason,
)


def _execution(
    *,
    triggered,
    already_airborne_event_type=None,
    throttle_release=False,
    control_completion=False,
):
    """Build one detected Mode-13 execution with optional trigger evidence."""
    events = []
    if triggered:
        events.append(
            TakeoffExecutionEvent(
                2_000_000,
                TakeoffExecutionEventType.TRIGGERED_AUTO,
                "Triggered AUTO. GPS speed = 2.0",
            )
        )
    if already_airborne_event_type is not None:
        detail = (
            "Above TKOFF alt - loitering"
            if already_airborne_event_type
            is TakeoffExecutionEventType.ALREADY_FLYING_ABOVE_TAKEOFF_ALT
            else "Climbing to TKOFF alt then loitering"
        )
        events.append(
            TakeoffExecutionEvent(
                1_500_000,
                already_airborne_event_type,
                detail,
            )
        )
    if throttle_release:
        events.append(
            TakeoffExecutionEvent(
                2_200_000,
                TakeoffExecutionEventType.THROTTLE_UNSUPPRESSED,
                "STAT.Sup=0",
            )
        )
    if control_completion:
        events.append(
            TakeoffExecutionEvent(
                2_500_000,
                TakeoffExecutionEventType.TAKEOFF_CONTROL_COMPLETED,
                "STAT.Stage TAKEOFF(1) -> NORMAL(3)",
            )
        )
    return TakeoffExecution(
        start_us=1_000_000,
        end_us=3_000_000,
        mission_item_number=None,
        command_id=None,
        termination_reason=TakeoffTerminationReason.MODE_EXIT,
        events=tuple(events),
        entry_context=TakeoffEntryContext.TAKEOFF_MODE,
    )


def _run_with_executions(monkeypatch, executions):
    """Run presentation with a normally loaded synthetic FlightLog."""
    flight_log = FlightLog()

    class _Reader:
        def __init__(self, _path, config=None):
            self.config = config

        def read(self):
            return flight_log

    monkeypatch.setattr(takeoff_module, "FlightReader", _Reader)
    monkeypatch.setattr(
        takeoff_module,
        "select_log_input",
        lambda: [Path("Logs/synthetic.bin")],
    )
    monkeypatch.setattr(
        takeoff_module.TakeoffExecutionDetector,
        "detect",
        lambda _self, _flight_log: executions,
    )
    TakeoffAnalysisPresentation(config=object()).run()


def test_menu_lists_and_dispatches_takeoff_analysis(monkeypatch, capsys):
    """Selection 10 invokes the TAKEOFF workflow and returns to the menu."""
    calls = []
    responses = iter(("10", "0"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        TakeoffAnalysisPresentation,
        "run",
        lambda _self: calls.append("run"),
    )

    analyse.menu()

    output = capsys.readouterr().out
    assert "10. Takeoff Analysis" in output
    assert calls == ["run"]
    assert output.count("Flight Analysis") == 2


def test_takeoff_presentation_uses_shared_selector_and_selected_log(monkeypatch):
    """The shared single-log selection is passed unchanged to FlightReader."""
    selected_path = Path("chosen/takeoff.BIN")
    config = object()
    selector_calls = []
    reader_calls = []

    def select_log():
        selector_calls.append(True)
        return [selected_path]

    class _Reader:
        def __init__(self, path, config=None):
            reader_calls.append((path, config))

        def read(self):
            return FlightLog()

    monkeypatch.setattr(takeoff_module, "select_log_input", select_log)
    monkeypatch.setattr(takeoff_module, "FlightReader", _Reader)
    monkeypatch.setattr(
        takeoff_module.TakeoffExecutionDetector,
        "detect",
        lambda _self, _flight_log: (),
    )

    TakeoffAnalysisPresentation(config=config).run()

    assert selector_calls == [True]
    assert reader_calls == [(selected_path, config)]


def test_takeoff_presentation_shared_selector_cancellation_stops_read(monkeypatch):
    """Cancelling the shared selector exits before opening a log."""
    reader_calls = []
    monkeypatch.setattr(takeoff_module, "select_log_input", lambda: None)
    monkeypatch.setattr(
        takeoff_module,
        "FlightReader",
        lambda *args, **kwargs: reader_calls.append((args, kwargs)),
    )

    TakeoffAnalysisPresentation(config=object()).run()

    assert reader_calls == []


def test_takeoff_presentation_handles_no_detected_executions(monkeypatch, capsys):
    """An empty detector result produces a concise operator message."""
    _run_with_executions(monkeypatch, ())

    assert "No TAKEOFF-mode executions found." in capsys.readouterr().out


def test_takeoff_presentation_handles_mode13_without_trigger(monkeypatch, capsys):
    """Detected Mode-13 windows without trigger evidence are not analysed."""
    _run_with_executions(
        monkeypatch,
        (_execution(triggered=False), _execution(triggered=False)),
    )

    output = capsys.readouterr().out
    assert (
        "2 TAKEOFF-mode executions detected; none contained a firmware launch trigger."
        in output
    )
    assert "TAKEOFF 1" not in output


def test_takeoff_presentation_uses_existing_pipeline_and_detected_count(
    monkeypatch,
    capsys,
):
    """Triggered results flow through the processor and multi-report formatter."""
    _run_with_executions(
        monkeypatch,
        (_execution(triggered=True), _execution(triggered=False)),
    )

    output = capsys.readouterr().out
    assert "2 TAKEOFF-mode executions detected" in output
    assert "1 triggered takeoff analysed" in output
    assert "1 non-trigger execution omitted" in output
    assert "Largest pitch tracking error" not in output
    assert "pitch residual" not in output.lower()
    assert "2000000" not in output


def test_takeoff_presentation_reports_only_explicit_already_airborne_context(
    monkeypatch,
    capsys,
):
    """Explicit firmware context is reported while arbitrary no-trigger is omitted."""
    above = _execution(
        triggered=False,
        already_airborne_event_type=(
            TakeoffExecutionEventType.ALREADY_FLYING_ABOVE_TAKEOFF_ALT
        ),
    )
    arbitrary = _execution(triggered=False)

    _run_with_executions(monkeypatch, (above, arbitrary))

    output = capsys.readouterr().out
    assert "2 TAKEOFF-mode executions detected" in output
    assert "0 triggered takeoffs analysed" in output
    assert "1 already-airborne TAKEOFF entry reported" in output
    assert "1 non-trigger execution omitted" in output
    assert "ALREADY-AIRBORNE TAKEOFF 1" in output
    assert (
        "Status                               Already airborne at TAKEOFF entry"
        in output
    )
    assert (
        "Takeoff profile                    Already airborne at TAKEOFF entry" in output
    )
    assert "Throttle release                   Unavailable" in output
    assert "TAKEOFF control                    Unavailable" in output
    assert "Trigger → AIRSPEED_MIN" not in output
    assert "Throttle → AIRSPEED_MIN" not in output
    assert "Altitude Δ at AIRSPEED_MIN" not in output
    assert "Airspeed source" not in output
    assert "Acceleration gate" not in output
    assert "GPS speed at trigger" not in output
    for classification in (
        "hand launch",
        "externally launched",
        "surface takeoff",
        "rolling takeoff",
    ):
        assert classification not in output.lower()


def test_below_target_airborne_context_retains_owned_throttle_and_censoring(
    monkeypatch,
    capsys,
):
    """Below-target context keeps suppression release without inventing trigger."""
    below = _execution(
        triggered=False,
        already_airborne_event_type=(
            TakeoffExecutionEventType.ALREADY_FLYING_CLIMB_TO_TAKEOFF_ALT
        ),
        throttle_release=True,
    )

    _run_with_executions(monkeypatch, (below,))

    output = capsys.readouterr().out
    assert "Throttle release                   Observed" in output
    assert "TAKEOFF control                    Mode exit before completion" in output
    assert "Trigger                            Observed" not in output
    assert "Trigger → AIRSPEED_MIN" not in output
    assert "Throttle → AIRSPEED_MIN" not in output


def test_already_airborne_context_preserves_owned_control_completion(
    monkeypatch,
    capsys,
):
    """An independently owned inner completion remains reportable."""
    below = _execution(
        triggered=False,
        already_airborne_event_type=(
            TakeoffExecutionEventType.ALREADY_FLYING_CLIMB_TO_TAKEOFF_ALT
        ),
        throttle_release=True,
        control_completion=True,
    )

    _run_with_executions(monkeypatch, (below,))

    output = capsys.readouterr().out
    assert "TAKEOFF control                    Completed" in output
