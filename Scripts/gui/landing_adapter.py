"""Qt-independent adapter for the existing Landing analysis pipeline."""

from pathlib import Path

from analyses.landing import LandingAnalysis, format_landing_log_report
from core.config import Config
from core.log_reader import FlightReader


def analyse_landing_log(log_path: Path) -> str:
    """Load one BIN and return the existing formatted Landing report."""
    path = Path(log_path)
    config = Config("Config/landing.yaml")
    flight_log = FlightReader(path, config=config).read()
    analysis = LandingAnalysis(config=config)
    results = tuple(
        analysis.analyse(flight_log, flight_window)
        for flight_window in flight_log.flights
    )
    return format_landing_log_report(path, results, len(flight_log.flights))
