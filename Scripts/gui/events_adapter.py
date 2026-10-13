"""Qt-independent adapter for the existing Event Timeline pipeline."""

from pathlib import Path

from analyses.event_timeline import format_event_timeline
from core.event_extractor import EventExtractor
from core.log_reader import FlightReader


def analyse_events_log(log_path: Path) -> str:
    """Load one BIN and return separate timelines for every detected flight."""
    path = Path(log_path)
    flight_log = FlightReader(path).read()
    if not flight_log.flights:
        return "\n".join(
            (
                "Event Timeline",
                "=" * 70,
                f"Log     : {path.name}",
                "Flights : 0",
                "",
                "No flights found.",
            )
        )

    extractor = EventExtractor()
    timelines = []
    for flight_index, flight_window in enumerate(flight_log.flights, start=1):
        events = extractor.extract(flight_log, flight_window)
        timelines.append(
            "\n".join(
                (
                    "=" * 70,
                    f"FLIGHT {flight_index}",
                    "=" * 70,
                    "",
                    format_event_timeline(path, flight_window, events),
                )
            )
        )
    return "\n\n".join(timelines)
