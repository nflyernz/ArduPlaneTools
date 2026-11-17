"""Qt-independent, read-only adapter for the Battery Analysis pipeline."""

from pathlib import Path

import pandas as pd

from analyses.battery import format_battery_report, format_voltage_failsafe_assessment
from core.battery import BatteryProcessor
from core.battery_failsafe import BATTERY_MESSAGE, assess_voltage_failsafe
from core.config import Config
from core.log_reader import FlightReader
from core.scope import filter_telemetry
from core.time import format_time


def _flight_battery_instances(flight_log, flight_window) -> list[int]:
    """Return valid BAT instance identifiers observed inside one flight."""
    battery = filter_telemetry(flight_log.get("BAT"), flight_window)
    if battery is None or battery.empty or "Inst" not in battery.columns:
        return []
    instances = pd.to_numeric(battery["Inst"], errors="coerce").dropna()
    return sorted({int(value) for value in instances})


def _flight_failsafe_message_instances(flight_log, flight_window) -> list[int]:
    """Identify battery instances explicitly named by in-flight MSG records."""
    messages = flight_log.get("MSG")
    if (
        messages is None
        or messages.empty
        or not {"TimeUS", "Message"}.issubset(messages.columns)
    ):
        return []
    messages = filter_telemetry(messages, flight_window)
    instances = set()
    for row in messages.itertuples(index=False):
        match = BATTERY_MESSAGE.search(str(row.Message))
        if match is not None and int(match.group(1)) > 0:
            instances.add(int(match.group(1)) - 1)
    return sorted(instances)


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
        instances = _flight_battery_instances(flight_log, flight_window)
        if not instances:
            message_instances = _flight_failsafe_message_instances(
                flight_log, flight_window
            )
            if message_instances:
                for instance in message_instances:
                    assessment = assess_voltage_failsafe(
                        flight_log, instance, flight_window
                    )
                    reports.append(
                        "\n".join(
                            (
                                "=" * 70,
                                f"FLIGHT {flight_index} — BATTERY INSTANCE {instance}",
                                "=" * 70,
                                "",
                                format_voltage_failsafe_assessment(assessment),
                            )
                        )
                    )
                continue
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
