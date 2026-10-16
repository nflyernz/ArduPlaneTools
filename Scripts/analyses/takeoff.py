"""User-facing workflow for Plane TAKEOFF-mode performance analysis."""

from analyses.log_selector import select_log_input
from core.config import Config
from core.log_reader import FlightReader, UnsupportedFirmwareError
from core.takeoff_execution import TakeoffEntryContext
from core.takeoff_execution_detector import TakeoffExecutionDetector
from core.takeoff_performance import (
    TakeoffPerformanceProcessor,
    TakeoffTelemetryRowCache,
    format_takeoff_performance_reports,
)


def analyse_takeoff_flight_log(flight_log, log_path) -> str:
    """Return the existing TAKEOFF report for one loaded flight log."""
    firmware = flight_log.firmware_version()
    lines = [
        "TAKEOFF Analysis",
        "================",
        f"Log: {log_path}",
        "Firmware: " + ((firmware or {}).get("version") or "Evidence unavailable"),
    ]

    executions = TakeoffExecutionDetector().detect(flight_log)
    takeoff_executions = tuple(
        execution
        for execution in executions
        if execution.entry_context is TakeoffEntryContext.TAKEOFF_MODE
    )
    if not takeoff_executions:
        return "\n".join((*lines, "", "No TAKEOFF-mode executions found."))

    row_cache = TakeoffTelemetryRowCache(flight_log)
    analyses = tuple(
        analysis
        for execution in takeoff_executions
        if (
            analysis := TakeoffPerformanceProcessor(
                flight_log,
                execution,
                row_cache,
            ).analyse()
        )
        is not None
    )
    already_airborne_executions = tuple(
        execution
        for execution in takeoff_executions
        if execution.already_airborne_entry is not None
        and execution.launch_trigger is None
    )
    if not analyses and not already_airborne_executions:
        count = len(takeoff_executions)
        noun = "execution" if count == 1 else "executions"
        return "\n".join(
            (
                *lines,
                "",
                f"{count} TAKEOFF-mode {noun} detected; "
                "none contained a firmware launch trigger.",
            )
        )

    return "\n".join(
        (
            *lines,
            "",
            format_takeoff_performance_reports(
                analyses,
                detected_execution_count=len(takeoff_executions),
                already_airborne_executions=already_airborne_executions,
            ),
        )
    )


class TakeoffAnalysisPresentation:
    """Load one log and present triggered TAKEOFF-mode execution evidence."""

    def __init__(self, config=None):
        self.config = config or Config("Config/landing.yaml")

    def run(self):
        """Select, analyse, and present one DataFlash log."""
        selected_logs = select_log_input()
        if selected_logs is None:
            return
        log_path = selected_logs[0]

        try:
            flight_log = FlightReader(log_path, config=self.config).read()
        except UnsupportedFirmwareError as exc:
            print()
            print("Unsupported firmware.")
            print(exc)
            return
        except OSError as exc:
            print()
            print(f"Unable to read log: {exc}")
            return

        print("\n" + analyse_takeoff_flight_log(flight_log, log_path))
