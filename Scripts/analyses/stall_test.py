"""User-facing FBWA stall-test evidence, without aerodynamic-stall claims."""

from dataclasses import dataclass
from math import isclose
from pathlib import Path
from statistics import mean, median

from core.config import Config
from core.log_reader import FlightReader, UnsupportedFirmwareError
from core.stall_departure_detector import StallTestAnalyzer
from core.stall_test import AirspeedQuality, StallStatus

from .log_selector import select_log_input
from .presentation_text import wrap_report


_LABELS = {
    StallStatus.PROBABLE_DEPARTURE: "Probable demand-opposed attitude departure",
    StallStatus.NO_DEMONSTRATED_DEPARTURE: "No demonstrated departure",
    StallStatus.AMBIGUOUS: "Ambiguous",
    StallStatus.REJECTED: "Rejected candidate",
}


@dataclass(frozen=True, slots=True)
class CleanIdleAirspeedSummary:
    """One same-flight, same-reference descriptive cohort of logged speeds."""

    attempt_numbers: tuple[int, ...]
    mean_m_s: float
    median_m_s: float
    minimum_m_s: float
    maximum_m_s: float

    @property
    def count(self):
        return len(self.attempt_numbers)


def _cohort_measurement(result):
    if (result.status is not StallStatus.PROBABLE_DEPARTURE
        or result.context is None
        or not result.context.clean_idle_context
        or result.context.mode != "FBWA"
        or result.airspeed is None):
        return None
    measurement = result.airspeed.raw_airspeed_at_pre_fall_pitch_peak
    if (measurement is None
        or measurement.quality is not AirspeedQuality.USABLE
        or measurement.sample is None
        or measurement.sample.source != "ARSP"
        or measurement.effective_ratio is None
        or measurement.sensor_instance != measurement.primary_instance
        or measurement.saved_parameters_at_sample is None):
        return None
    return measurement


def _provenance_key(measurement):
    parameters = measurement.saved_parameters_at_sample.values
    return (
        measurement.sensor_instance,
        parameters.get("ARSPD_TYPE"), parameters.get("ARSPD_USE"),
        parameters.get("ARSPD_TUBE_ORDR"),
        parameters.get("ARSPD_OFFSET"), parameters.get("ARSPD_AUTOCAL"),
    )


def summarize_clean_idle_airspeed(flight_result):
    """Summarize only a compatible clean-idle probable cohort of size >= 2."""
    candidates = [
        (number, measurement)
        for number, result in enumerate(flight_result.results, start=1)
        if (measurement := _cohort_measurement(result)) is not None
    ]
    if len(candidates) < 2:
        return None
    first = candidates[0][1]
    key = _provenance_key(first)
    # Same-row ratios contain float logging noise. A difference greater than
    # 0.01% suppresses a single-cohort mean rather than mixing calibrations.
    if any(
        _provenance_key(item) != key
        or not isclose(item.effective_ratio, first.effective_ratio,
                       rel_tol=0.0001, abs_tol=0.0001)
        for _, item in candidates[1:]
    ):
        return None
    speeds = [item.sample.value for _, item in candidates]
    return CleanIdleAirspeedSummary(
        attempt_numbers=tuple(number for number, _ in candidates),
        mean_m_s=mean(speeds), median_m_s=median(speeds),
        minimum_m_s=min(speeds), maximum_m_s=max(speeds),
    )


def _time(time_us):
    return f"{time_us / 1_000_000:.3f} s"


def _point(point, unit=""):
    if point is None:
        return "unavailable"
    return f"{point.value:.2f}{unit} at {_time(point.time_us)}"


def _airspeed_line(label, measurement):
    if measurement is None or measurement.sample is None:
        return f"  {label}: unavailable"
    if measurement.quality is not AirspeedQuality.USABLE:
        detail = "; ".join(measurement.warnings) or measurement.quality.value
        return f"  {label}: unavailable ({detail})"
    return (
        f"  {label}: {measurement.sample.value:.2f} m/s "
        f"(raw ARSP, instance {measurement.sensor_instance}, "
        f"logged {_time(measurement.sample.time_us)}, "
        f"reference {_time(measurement.reference_us)}, "
        f"gap {measurement.association_gap_us / 1_000:.0f} ms)"
    )


def _calibration_line(measurement):
    if measurement is None:
        return None
    saved = measurement.saved_parameters
    values = saved.values if saved else {}
    ratio = values.get("ARSPD_RATIO")
    configured = f"{ratio:.4f}" if ratio is not None else "unavailable"
    if measurement.quality is not AirspeedQuality.USABLE:
        effective = "unavailable (unusable ARSP evidence)"
    elif measurement.effective_ratio is not None:
        effective = f"{measurement.effective_ratio:.4f}"
    else:
        effective = "unavailable (unsupported)"
    autocal = values.get("ARSPD_AUTOCAL")
    autocal_label = {0: "off", 1: "on"}.get(autocal, "unknown")
    line = (
        f"  Airspeed calibration: saved ARSPD_RATIO {configured}; "
        f"effective airspeed ratio {effective}; AUTOCAL {autocal_label}"
    )
    if (measurement.saved_parameters_at_sample is not None
        and measurement.saved_parameters_at_sample.values.get("ARSPD_RATIO")
        != ratio):
        sampled = measurement.saved_parameters_at_sample.values["ARSPD_RATIO"]
        sampled_label = f"{sampled:.4f}" if sampled is not None else "unavailable"
        line += f"; saved ratio at ARSP row {sampled_label}"
    return line


def _format_context(result):
    context = result.context
    if context is None:
        return "  Context: unavailable"
    details = [
        f"{context.mode}",
        context.throttle_class.replace("_", " "),
        context.bank_class.replace("_", " "),
    ]
    if context.median_commanded_throttle_percent is not None:
        details.append(
            f"median commanded throttle {context.median_commanded_throttle_percent:.1f}%"
        )
    if context.flap_command is not None:
        details.append(f"logged flap command {context.flap_command:.1f}")
    return "  Context: " + "; ".join(details)


def _format_response(result):
    response = result.response
    if response is None:
        return []
    error = response.target_at_peak.value - response.pitch_peak.value
    lines = [
        f"  Logged pitch peak {_time(response.pitch_peak.time_us)}; "
        f"first opposed-fall observation {_time(response.first_opposed_fall.time_us)}",
        f"  At peak: pilot nose-up RCIN {response.pilot_at_peak.value:.0f} PWM; "
        f"FBWA target {response.target_at_peak.value:.1f}°; "
        f"actual pitch {response.pitch_peak.value:.1f}°; "
        f"target−actual error {error:+.1f}°",
        f"  Observed opposed fall {response.pitch_fall_deg:.1f}°; "
        f"error growth {response.error_growth_deg:.1f}° by confirmation",
    ]
    if result.departure is not None:
        event = result.departure
        lines.append(
            "  Logged elevator command/output endpoint: "
            f"AETR.Elev {event.aetr_endpoint.value:.0f}; "
            f"RCOU.C{event.elevator_channel} {event.rcou_endpoint.value:.0f} PWM"
        )
    return lines


def _format_recovery(result):
    if result.status is not StallStatus.PROBABLE_DEPARTURE:
        return []
    recovery = result.recovery
    if recovery is None:
        return ["  Recovery-control action: not observed; no completion inferred"]
    actions = [
        name for point, name in (
            (recovery.pilot_demand_reduction, "pilot demand reduction"),
            (recovery.target_reduction, "target reduction"),
            (recovery.commanded_power_increase, "commanded power increase"),
        ) if point is not None
    ]
    lines = [
        f"  Recovery-control observation: {_time(recovery.control_start.time_us)} "
        f"({', '.join(actions)})",
    ]
    if recovery.pitch_minimum is not None:
        line = f"  Minimum measured pitch after control action: {_point(recovery.pitch_minimum, '°')}"
        if recovery.pitch_limit_min_deg is not None:
            line += f"; configured PTCH_LIM_MIN_DEG {recovery.pitch_limit_min_deg:.1f}°"
        lines.append(line)
    if recovery.attitude_below_target_limit:
        line = "  Measured attitude exceeded the configured negative target limit"
        if (recovery.nose_up_elevator_command is not None
            and recovery.nose_up_elevator_pwm_command is not None):
            line += "; logged elevator command/output there indicate nose-up correction"
        lines.append(line)
    if recovery.first_sustained_airspeed_increase is not None:
        lines.append(
            "  First observed sustained raw-airspeed increase: "
            + _point(recovery.first_sustained_airspeed_increase, " m/s")
        )
    if recovery.lowest_altitude_after_departure is not None:
        line = (
            "  Lowest BARO altitude after departure reference: "
            + _point(recovery.lowest_altitude_after_departure, " m")
        )
        if recovery.altitude_loss_from_departure_reference_m is not None:
            line += (
                "; decrease from departure-reference BARO altitude "
                f"{recovery.altitude_loss_from_departure_reference_m:.1f} m"
            )
        lines.append(line)
    if recovery.sink_arrest is not None:
        lines.append(f"  Observed sink arrest: {_time(recovery.sink_arrest.time_us)}")
    return lines


def format_stall_attempt(result, number):
    """Format one retained attempt/candidate without changing its status."""
    attempt = result.attempt
    noun = "Candidate" if result.status is StallStatus.REJECTED else "Attempt"
    lines = [
        f"{noun} {number}: {_time(attempt.start_us)}–{_time(attempt.end_us)} "
        f"| {_LABELS[result.status]}",
    ]
    if result.status is StallStatus.REJECTED:
        if result.reasons:
            lines[0] += " (" + ", ".join(
                reason.value.replace("_", " ") for reason in result.reasons
            ) + ")"
        return lines[0]
    lines.append(_format_context(result))
    if result.reasons:
        lines.append(
            "  Evidence notes: "
            + ", ".join(reason.value.replace("_", " ") for reason in result.reasons)
        )
    lines.extend(_format_response(result))
    air = result.airspeed
    if air is not None:
        for label, measurement in (
            ("Pre-fall pitch-peak airspeed", air.raw_airspeed_at_pre_fall_pitch_peak),
            ("First opposed-fall airspeed", air.raw_airspeed_at_first_opposed_fall_observation),
            ("Minimum usable airspeed", air.lowest_usable_raw_airspeed_in_attempt),
            ("Recovery-control-start airspeed", air.raw_airspeed_at_recovery_start),
            ("Later recovery speed milestone", air.raw_airspeed_at_observed_recovery_milestone),
        ):
            if measurement is not None or label == "Minimum usable airspeed":
                lines.append(_airspeed_line(label, measurement))
        reference = (
            air.raw_airspeed_at_pre_fall_pitch_peak
            or air.lowest_usable_raw_airspeed_in_attempt
        )
        calibration = _calibration_line(reference)
        if calibration:
            lines.append(calibration)
        if (reference is not None and reference.warnings
            and reference.quality is AirspeedQuality.USABLE):
            lines.append("  Airspeed note: " + "; ".join(reference.warnings))
    if result.status is StallStatus.PROBABLE_DEPARTURE:
        if result.context is None or not result.context.clean_idle_context:
            lines.append(
                "  Summary note: excluded from clean-idle mean "
                "(throttle, bank or flap context differs/unknown)"
            )
        elif _cohort_measurement(result) is None:
            lines.append(
                "  Summary note: excluded from clean-idle mean "
                "(usable pitch-peak speed or effective calibration unavailable)"
            )
    lines.extend(_format_recovery(result))
    return "\n".join(lines)


def format_stall_flight_report(flight_result, flight_number):
    """Format one FlightWindow and its descriptive same-flight summary."""
    window = flight_result.flight_window
    lines = [
        f"Flight {flight_number} | {_time(window.start_us)}–{_time(window.end_us)}",
        "-" * 58,
    ]
    if not flight_result.results:
        lines.append("No analyzable FBWA stall-test attempts found.")
    else:
        if all(result.status is StallStatus.REJECTED
               for result in flight_result.results):
            lines.append("No analyzable FBWA stall-test attempts found.")
        for number, result in enumerate(flight_result.results, start=1):
            lines.extend(("", format_stall_attempt(result, number)))
    counts = {status: sum(result.status is status for result in flight_result.results)
              for status in StallStatus}
    lines.extend((
        "", "Flight classification summary:",
        f"  Probable departures: {counts[StallStatus.PROBABLE_DEPARTURE]}",
        f"  No demonstrated departures: {counts[StallStatus.NO_DEMONSTRATED_DEPARTURE]}",
        f"  Ambiguous attempts: {counts[StallStatus.AMBIGUOUS]}",
        f"  Rejected candidates: {counts[StallStatus.REJECTED]}",
    ))
    summary = summarize_clean_idle_airspeed(flight_result)
    if summary is None:
        lines.append(
            "  No comparable clean-idle probable-departure cohort "
            "of at least two events; no mean reported."
        )
    else:
        lines.extend((
            "  Comparable clean-idle probable departures: "
            f"{summary.count} (attempts {', '.join(map(str, summary.attempt_numbers))})",
            "  Raw pre-fall pitch-peak airspeed: "
            f"mean {summary.mean_m_s:.2f} m/s; "
            f"median {summary.median_m_s:.2f} m/s; "
            f"range {summary.minimum_m_s:.2f}–{summary.maximum_m_s:.2f} m/s",
        ))
    return "\n".join(lines)


def format_stall_report(flight_results):
    """Present each detected flight independently; never aggregate across them."""
    lines = ["FBWA Stall-Test Prototype", "========================="]
    if not flight_results:
        lines.append("No detected flight windows to analyse.")
    else:
        first = flight_results[0]
        lines.extend((
            f"Log: {Path(first.log_file).name if first.log_file else 'unavailable'}",
            f"Firmware: {first.firmware_version or 'unavailable'}",
            f"Prototype rules: {first.rule_version}",
        ))
    for number, result in enumerate(flight_results, start=1):
        lines.extend(("", format_stall_flight_report(result, number)))
    return "\n".join(lines)


class StallAnalysisPresentation:
    """Select a BIN through APT's shared selector and present core results."""

    def __init__(self, config=None):
        self.config = config or Config("Config/stall_test.yaml")

    def run(self):
        selected = select_log_input()
        if not selected:
            return
        try:
            log = FlightReader(selected[0], config=self.config).read()
        except (UnsupportedFirmwareError, OSError) as exc:
            print(f"\nStall Analysis unavailable: {exc}")
            return
        analyzer = StallTestAnalyzer(self.config)
        results = tuple(analyzer.analyse(log, flight) for flight in log.flights)
        print("\n" + wrap_report(format_stall_report(results)))
