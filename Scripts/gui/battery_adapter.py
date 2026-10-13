"""Qt-independent, read-only adapter for the Battery Analysis pipeline."""

from pathlib import Path

from analyses.battery import format_battery_report
from core.battery import BatteryProcessor
from core.config import Config
from core.log_reader import FlightReader
from core.time import format_time


def analyse_battery_log(log_path: Path) -> str:
    """Load one BIN and report each flight and BAT instance without persistence."""
    path = Path(log_path)
    config = Config("Config/battery.yaml")
    flight_log = FlightReader(path, config=config).read()
    if not flight_log.flights:
        return "\n".join(
            (
                "BATTERY ANALYSIS",
                "=" * 70,
                f"Log     : {path.name}",
                "Flights : 0",
                "",
                "No flights found.",
            )
        )

    reports = []
    for flight_index, flight_window in enumerate(flight_log.flights, start=1):
        instances = BatteryProcessor(
            flight_log,
            flight_window,
            0,
            config=config,
        ).available_instances()
        if not instances:
            reports.append(
                "\n".join(
                    (
                        "=" * 70,
                        f"FLIGHT {flight_index}",
                        "=" * 70,
                        "",
                        "Window : "
                        f"{format_time(flight_window.start_us)} -> "
                        f"{format_time(flight_window.end_us)}",
                        "",
                        "No battery telemetry is available for this flight.",
                    )
                )
            )
            continue

        for instance in instances:
            analysis = BatteryProcessor(
                flight_log,
                flight_window,
                instance,
                config=config,
            ).analyse()
            reports.append(
                "\n".join(
                    (
                        "=" * 70,
                        f"FLIGHT {flight_index} — BATTERY INSTANCE {instance}",
                        "=" * 70,
                        "",
                        format_battery_report(
                            path,
                            flight_window,
                            analysis,
                        ),
                    )
                )
            )
    return "\n\n".join(reports)
