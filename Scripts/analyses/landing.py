"""
Landing analysis workflow.

User-facing presentation for the landing-analysis pipeline.
"""

from pathlib import Path

from analyses.log_selector import select_log_input
from analyses.result import AnalysisResult
from core.config import Config
from core.landing_attempt_extractor import (
    LandingAttemptExtractor,
)
from core.landing_attempt_processor import (
    LandingAttemptProcessor,
)
from core.landing_window_detector import (
    LandingWindowDetector,
)
from core.log_reader import (
    FlightReader,
    UnsupportedFirmwareError,
)
from core.time import format_time_us


def _format_row(label, value):
    return f"{label:<28}{value}"


def _format_value(value, decimals=1, suffix=""):
    if value is None:
        return "Unavailable"
    return f"{value:.{decimals}f}{suffix}"


def _format_time(time_us):
    if time_us is None:
        return "Unavailable"
    return format_time_us(time_us)


def _has_rangefinder_evidence(analysis):
    return any(
        value is not None
        for value in (
            analysis.rangefinder_first_nonzero_time_us,
            analysis.rangefinder_first_nonzero_distance,
            analysis.rangefinder_first_in_range_time_us,
            analysis.rangefinder_first_in_range_distance,
            analysis.rangefinder_continuous_time_us,
        )
    )


def _format_end_reason(reason):
    labels = {
        "gps": "GPS stop",
        "abort": "Landing aborted",
        "flight_window_end": "Flight ended before landing stop detected",
    }
    return labels.get(reason, str(reason))


def format_landing_attempt(landing_index, attempt_index, analysis) -> str:
    """Return the existing CLI presentation for one landing attempt."""
    attempt = analysis.attempt
    lines = [
        f"Landing {landing_index} Attempt {attempt_index}",
        "-" * 70,
        _format_row(
            "Landing window",
            f"{format_time_us(attempt.start_us)} -> {format_time_us(attempt.end_us)}",
        ),
        _format_row("Landing duration", _format_value(analysis.duration_s, 1, " s")),
        "",
        "APPROACH",
        _format_row(
            "Approach altitude",
            _format_value(analysis.approach_start_altitude, 1, " m"),
        ),
        _format_row(
            "Glide slope", _format_value(analysis.glide_slope_degrees, 1, " deg")
        ),
        "",
        "PREFLARE",
        _format_row("Time", _format_time(analysis.preflare_time_us)),
        _format_row(
            "Preflare height", _format_value(analysis.preflare_altitude, 1, " m")
        ),
        _format_row("Airspeed", _format_value(analysis.preflare_airspeed, 1, " m/s")),
        _format_row(
            "GPS groundspeed", _format_value(analysis.preflare_gps_speed, 1, " m/s")
        ),
        _format_row(
            "Sink rate", _format_value(analysis.preflare_sink_rate, 1, " m/s")
        ),
        "",
        "FLARE",
        _format_row("Time", _format_time(analysis.flare_time_us)),
        _format_row(
            "Flare-timing height", _format_value(analysis.flare_altitude, 1, " m")
        ),
        _format_row("Sink rate", _format_value(analysis.flare_sink_rate, 1, " m/s")),
        _format_row("Airspeed", _format_value(analysis.flare_airspeed, 1, " m/s")),
        _format_row(
            "GPS groundspeed", _format_value(analysis.flare_gps_speed, 1, " m/s")
        ),
        _format_row(
            "Flare distance to target",
            _format_value(analysis.flare_distance, 1, " m"),
        ),
    ]

    if _has_rangefinder_evidence(analysis):
        lines.extend(
            (
                "",
                "RANGEFINDER",
                _format_row(
                    "First non-zero",
                    _format_time(analysis.rangefinder_first_nonzero_time_us),
                ),
                _format_row(
                    "First distance",
                    _format_value(
                        analysis.rangefinder_first_nonzero_distance, 1, " m"
                    ),
                ),
                _format_row(
                    "First in range",
                    _format_time(analysis.rangefinder_first_in_range_time_us),
                ),
                _format_row(
                    "In-range distance",
                    _format_value(
                        analysis.rangefinder_first_in_range_distance, 1, " m"
                    ),
                ),
                _format_row(
                    "Continuous from",
                    _format_time(analysis.rangefinder_continuous_time_us),
                ),
            )
        )

    lines.extend(("", "LANDING / ROLLOUT COMPLETION"))
    if analysis.gps_stop_time_us is not None:
        lines.extend(
            (
                _format_row("GPS stop", _format_time(analysis.gps_stop_time_us)),
                _format_row(
                    "Flare -> stop",
                    _format_value(analysis.flare_to_gps_stop_s, 1, " s"),
                ),
                _format_row(
                    "Distance from target",
                    _format_value(analysis.landing_end_target_distance_m, 1, " m"),
                ),
            )
        )
    lines.append(_format_row("End reason", _format_end_reason(analysis.end_reason)))
    return "\n".join(lines)


def format_landing_flight_result(result: AnalysisResult, flight_index: int) -> str:
    """Return the existing CLI presentation for one detected flight window."""
    lines = ["=" * 70, "", f"FLIGHT {flight_index}", "", "=" * 70]
    analyses = result.report or []
    if not analyses:
        lines.extend(("", "No landing attempts detected."))
    else:
        for landing_index, attempt_index, analysis in analyses:
            lines.extend(("", format_landing_attempt(landing_index, attempt_index, analysis)))
    return "\n".join(lines)


def format_landing_log_report(log_path: Path, flight_results, flight_count: int) -> str:
    """Return the CLI-equivalent report and summary for one successfully read BIN."""
    results = tuple(flight_results)
    lines = [
        "Landing Analysis",
        "=" * 70,
        "",
        "Found 1 log(s)",
        "",
        f"[  1/1] {Path(log_path).name}",
        f"Loaded: {flight_count} flight(s)",
    ]
    if flight_count == 0:
        lines.append("No flights detected.")
    else:
        for flight_index, result in enumerate(results, start=1):
            lines.extend(("", format_landing_flight_result(result, flight_index)))
    lines.extend(
        (
            "",
            "=" * 70,
            "",
            "SUMMARY",
            "",
            _format_row("Logs", "1"),
            _format_row("Flight results", str(len(results))),
            _format_row("Framework errors", "0"),
        )
    )
    return "\n".join(lines)


class LandingAnalysis:
    """
    Landing analysis.

    Workflow:

        1. Select log(s)
        2. Load telemetry
        3. Process each FlightWindow
        4. Detect LandingWindows
        5. Extract LandingAttempts
        6. Build measured landing evidence
        7. Present the result

    Core landing-analysis code is responsible for measurement and
    event extraction. This class handles workflow and presentation.
    """

    def __init__(
        self,
        config=None,
    ):
        self.config = config or Config(
            "Config/landing.yaml"
        )

    def analyse(
        self,
        flight_log,
        flight_window,
    ) -> AnalysisResult:
        """
        Analyse one canonical FlightWindow.

        This method performs analysis only. It does not handle
        CLI input or presentation.
        """

        landing_windows = (
            LandingWindowDetector(
                self.config
            ).detect(
                flight_log,
                flight_window,
            )
        )

        analyses = []

        extractor = LandingAttemptExtractor(
            flight_log
        )

        for landing_index, landing_window in enumerate(
            landing_windows,
            start=1,
        ):

            attempts = extractor.extract(
                landing_window
            )

            for attempt_index, attempt in enumerate(
                attempts,
                start=1,
            ):

                analysis = LandingAttemptProcessor(
                    flight_log,
                    flight_window,
                    landing_window,
                    attempt,
                    self.config,
                ).build()

                analyses.append(
                    (
                        landing_index,
                        attempt_index,
                        analysis,
                    )
                )

        log_path = Path(
            flight_log.metadata["log_file"]
        )

        return AnalysisResult(
            flight_log=flight_log,
            log_path=log_path,
            flight_window=flight_window,
            landing_windows=landing_windows,
            report=analyses,
        )

    def present_result(
        self,
        result: AnalysisResult,
        flight_index: int,
    ):
        """
        Present one FlightWindow landing-analysis result.
        """

        print("\n" + format_landing_flight_result(result, flight_index))

    def _present_attempt(
        self,
        landing_index,
        attempt_index,
        analysis,
    ):
        """
        Present one LandingAttemptAnalysis.
        """

        print("\n" + format_landing_attempt(landing_index, attempt_index, analysis))

    def run(self):
        """
        Run landing analysis from the CLI menu.
        """

        logs = select_log_input(allow_directory=True)

        if not logs:
            return []

        results = []
        framework_errors = 0

        print()
        print("Landing Analysis")
        print("=" * 70)

        print()
        print(
            f"Found {len(logs)} log(s)"
        )

        for log_index, log_path in enumerate(
            logs,
            start=1,
        ):

            print()
            print(
                f"[{log_index:>3}/{len(logs)}] "
                f"{log_path.name}"
            )

            try:

                flight_log = self.load_telemetry(
                    log_path
                )

                print(
                    f"Loaded: "
                    f"{len(flight_log.flights)} "
                    f"flight(s)"
                )

                if not flight_log.flights:
                    print(
                        "No flights detected."
                    )
                    continue

                for (
                    flight_index,
                    flight_window,
                ) in enumerate(
                    flight_log.flights,
                    start=1,
                ):

                    result = self.analyse(
                        flight_log,
                        flight_window,
                    )

                    results.append(
                        result
                    )

                    self.present_result(
                        result,
                        flight_index,
                    )

            except UnsupportedFirmwareError as ex:

                print(
                    f"Unsupported firmware: {ex}"
                )

                framework_errors += 1

            except OSError as ex:

                print(
                    f"Unable to read log: {ex}"
                )

                framework_errors += 1

        print()
        print("=" * 70)
        print()
        print("SUMMARY")
        print()

        self._row(
            "Logs",
            str(
                len(logs)
            ),
        )

        self._row(
            "Flight results",
            str(
                len(results)
            ),
        )

        self._row(
            "Framework errors",
            str(
                framework_errors
            ),
        )

        return results

    def load_telemetry(
        self,
        log_path,
    ):
        """
        Load one ArduPilot BIN log.
        """

        reader = FlightReader(
            log_path,
            config=self.config,
        )

        return reader.read()

    @staticmethod
    def _row(
        label,
        value,
    ):
        """
        Print one aligned report row.
        """

        print(
            f"{label:<28}{value}"
        )

    @staticmethod
    def _value(
        value,
        decimals=1,
        suffix="",
    ):
        """
        Format an optional numeric value.
        """

        if value is None:
            return "Unavailable"

        return (
            f"{value:.{decimals}f}"
            f"{suffix}"
        )

    @staticmethod
    def _time(
        time_us,
    ):
        """
        Format an optional TimeUS value.
        """

        if time_us is None:
            return "Unavailable"

        return format_time_us(
            time_us
        )

    @staticmethod
    def _has_rangefinder_evidence(
        analysis,
    ):
        """
        True when the attempt contains rangefinder evidence.

        Rangefinder is an optional sensor.
        """

        return any(
            value is not None
            for value in (
                analysis
                .rangefinder_first_nonzero_time_us,

                analysis
                .rangefinder_first_nonzero_distance,

                analysis
                .rangefinder_first_in_range_time_us,

                analysis
                .rangefinder_first_in_range_distance,

                analysis
                .rangefinder_continuous_time_us,
            )
        )

    @staticmethod
    def _end_reason(
        reason,
    ):
        """
        Convert internal landing-window termination reason into
        user-facing factual wording.
        """

        labels = {
            "gps": "GPS stop",
            "abort": "Landing aborted",
            "flight_window_end": (
                "Flight ended before landing stop detected"
            ),
        }

        return labels.get(
            reason,
            str(reason),
        )
