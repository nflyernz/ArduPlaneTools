"""Qt-independent adapter for the existing AUTOTUNE analysis pipeline."""

from pathlib import Path

from analyses.autotune import format_autotune_report
from core.autotune_detector import AutotuneDetector
from core.config import Config
from core.log_reader import FlightReader


def analyse_autotune_log(log_path: Path) -> str:
    """Load one BIN and return the existing formatted AUTOTUNE report."""
    path = Path(log_path)
    flight_log = FlightReader(
        path,
        config=Config("Config/autotune.yaml"),
    ).read()
    result = AutotuneDetector().detect(flight_log)
    return format_autotune_report(result, path)
