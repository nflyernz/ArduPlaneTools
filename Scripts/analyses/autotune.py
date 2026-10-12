"""Single-log AUTOTUNE review, consuming structured detector evidence only."""

from core.autotune import (
    AutotuneAxis,
    AutotuneExitOutcome,
    AutotuneTerminationReason,
)
from core.autotune_detector import AutotuneDetector
from core.config import Config
from core.log_reader import FlightReader, UnsupportedFirmwareError

from .log_selector import select_log_input


def _axes(axes):
    if axes is None:
        return "Evidence unavailable"
    return ", ".join(axis.name.title() for axis in axes) or "None"


def _runtime(gains):
    if gains is None:
        return "Evidence unavailable"
    return ", ".join(
        f"{name.upper()}={getattr(gains, name):.6g}"
        if getattr(gains, name) is not None
        else f"{name.upper()} unavailable"
        for name in ("ff", "p", "i", "d", "rmax", "tau")
    )


def _flight_association(relations):
    if not relations:
        return "None detected"
    if len(relations) == 1:
        return f"Flight {relations[0].flight_number}"
    return "Flights " + ", ".join(str(relation.flight_number) for relation in relations)


def format_autotune_report(result, log_path=None):
    """Format evidence without re-reading or interpreting raw log records."""
    lines = [
        "AUTOTUNE Review",
        "===============",
        f"Log: {log_path if log_path is not None else 'Unavailable'}",
        f"Firmware: {result.firmware or 'Evidence unavailable'}",
        f"Sessions: {len(result.sessions)}",
    ]
    for session in result.sessions:
        duration = (
            f"{session.duration_s:.3f} s"
            if session.duration_s is not None
            else "Evidence unavailable"
        )
        lines.extend(
            [
                "",
                f"Session {session.number}: {duration} — {session.termination_reason.value}",
                f"  Started: {session.start.time_us / 1e6:.6f} s; source order {session.start.source_order}",
                f"  End: {session.end.time_us / 1e6:.6f} s; source order {session.end.source_order}"
                if session.end
                else "  End: Evidence unavailable",
                f"  Configured at session start: {_axes(session.configured_axes)}",
                f"  Selected: {_axes(session.selected_axes)}",
                f"  Tuning activity observed: {_axes(session.active_axes)}",
                "  Configuration: "
                + ", ".join(
                    f"{name}={value if value is not None else 'unavailable'}"
                    for name, value in session.configuration.items()
                ),
                f"  Flight association: {_flight_association(session.flight_relations)}",
            ]
        )
        for relation in session.flight_relations:
            if relation.starts_before_flight:
                lines.append(
                    f"  Session starts before detected Flight {relation.flight_number}"
                )
        if session.termination_reason is not AutotuneTerminationReason.STOPPED:
            lines.append("  Normal stop not observed")
        for axis, evidence in session.axes.items():
            lines.extend(
                [
                    "",
                    f"  {axis.name.title()}: Tuning activity {'observed' if evidence.active else 'not observed'} ({evidence.atrp_count} ATRP records)",
                ]
            )
            if evidence.active:
                lines.extend(
                    [
                        f"    Demand periods: {len(evidence.demand_periods)} (positive {evidence.positive_demand_periods}, negative {evidence.negative_demand_periods})",
                        f"    Observed demand time: {evidence.total_observed_demand_time_s:.3f} s; longest {evidence.longest_observed_demand_period_s:.3f} s",
                        f"    Action baseline: {evidence.action_baseline}; transitions: {len(evidence.action_transitions)}",
                        f"    Entry runtime gains: {_runtime(evidence.entry_runtime_gains)}",
                        f"    Final observed runtime gains: {_runtime(evidence.final_observed_runtime_gains)}",
                    ]
                )
            elif (
                axis is AutotuneAxis.YAW
                and session.selected_axes is not None
                and axis in session.selected_axes
                and session.configuration.get("YAW_RATE_ENABLE") == 0
            ):
                lines.append("    selected; YAW_RATE_ENABLE=0")
            events = sorted(
                [*evidence.gain_limit_events, *evidence.completion_events],
                key=lambda event: event.position.key,
            )
            for event in events:
                if hasattr(event, "kind"):
                    lines.append(
                        f"    {event.kind}-limit event: {event.value:.6g} at {event.position.time_us / 1e6:.6f} s"
                    )
                else:
                    lines.append(
                        f"    Completion milestone observed at {event.position.time_us / 1e6:.6f} s; Save requested by firmware milestone"
                    )
            if not evidence.completion_events:
                lines.append("    Completion milestone not observed")
            persistence = evidence.persistence
            outcome = {
                AutotuneExitOutcome.SAVE_REQUESTED: "Save requested on exit",
                AutotuneExitOutcome.RESTORE_INFERRED: "Restore path inferred",
                AutotuneExitOutcome.UNKNOWN: "Evidence unavailable for exit save/restore",
            }[persistence.exit_outcome]
            lines.append(f"    {outcome}")
            if persistence.exit_outcome is AutotuneExitOutcome.RESTORE_INFERRED:
                lines.append(f"      {persistence.exit_basis}")
            lines.append(
                f"    Parameter-save records observed: {len(persistence.parameter_save_observations)}"
            )
            for observation in persistence.parameter_save_observations:
                lines.append(
                    f"      {observation.name}={observation.value:.6g} at {observation.position.time_us / 1e6:.6f} s ({observation.trigger.trigger_type.value})"
                )
            if persistence.runtime_continuity_from_session is not None:
                lines.append(
                    f"    Runtime gain continuity observed from Session {persistence.runtime_continuity_from_session}"
                )
    if not result.sessions:
        lines.append("No authoritative AUTOTUNE sessions found.")
    if result.warnings:
        lines.extend(["", "Evidence warnings:"])
        for warning in result.warnings:
            context = (
                f"Session {warning.session_number}: " if warning.session_number else ""
            )
            at = (
                f" at {warning.position.time_us / 1e6:.6f} s (source {warning.position.source_order})"
                if warning.position
                else ""
            )
            lines.append(f"  {warning.code}: {context}{warning.detail}{at}")
    return "\n".join(lines)


class AutotuneAnalysisPresentation:
    def __init__(self, config=None):
        self.config = config or Config("Config/autotune.yaml")

    def run(self):
        selection = select_log_input()
        if not selection:
            return
        try:
            flight_log = FlightReader(selection[0], config=self.config).read()
        except UnsupportedFirmwareError as exc:
            print(f"\nUnsupported firmware.\n{exc}")
            return
        except OSError as exc:
            print(f"\nUnable to read log: {exc}")
            return
        result = AutotuneDetector().detect(flight_log)
        print("\n" + format_autotune_report(result, selection[0]))
