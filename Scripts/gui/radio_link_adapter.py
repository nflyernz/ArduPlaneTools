"""Qt-independent adapter for aircraft-BIN Radio Link analysis."""

from dataclasses import dataclass
from pathlib import Path

from analyses.radio_link import (
    format_radio_link_report,
    format_radio_link_summary,
)
from core.config import Config
from core.log_reader import FlightReader
from core.radio_link import RadioLinkDetector


@dataclass(frozen=True)
class RadioLinkGuiResult:
    """Both existing BIN report views tied to one source file."""

    source_path: Path
    summary: str
    detail: str


def analyse_radio_link_log(log_path: Path) -> RadioLinkGuiResult:
    """Read and detect once, then format both existing aircraft-BIN views."""
    path = Path(log_path).resolve()
    config = Config("Config/radio_link.yaml")
    flight_log = FlightReader(path, config=config).read()
    result = RadioLinkDetector().detect(flight_log)
    return RadioLinkGuiResult(
        path,
        format_radio_link_summary(result, path, flight_log),
        format_radio_link_report(result, path),
    )
