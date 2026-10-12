"""Qt-independent adapter for the existing TAKEOFF analysis pipeline."""

from pathlib import Path

from analyses.takeoff import analyse_takeoff_flight_log
from core.config import Config
from core.log_reader import FlightReader


def analyse_takeoff_log(log_path: Path) -> str:
    """Load one BIN and return the existing formatted TAKEOFF report."""
    path = Path(log_path)
    flight_log = FlightReader(
        path,
        config=Config("Config/landing.yaml"),
    ).read()
    return analyse_takeoff_flight_log(flight_log, path)
