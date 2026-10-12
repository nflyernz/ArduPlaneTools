"""Qt-independent adapter for the existing Stall analysis pipeline."""

from pathlib import Path

from analyses.stall import analyse_stall_flight_log
from core.config import Config
from core.log_reader import FlightReader


def analyse_stall_log(log_path: Path) -> str:
    """Load one BIN and return the existing formatted Stall report."""
    path = Path(log_path)
    config = Config("Config/stall_test.yaml")
    flight_log = FlightReader(path, config=config).read()
    return analyse_stall_flight_log(flight_log, config)
