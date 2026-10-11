"""Classify ordered FBWA command/response evidence inside extracted pulls."""

from bisect import bisect_left, bisect_right
from dataclasses import replace
from statistics import median

from .stall_attempt_extractor import StallAttemptExtractor, usable_airspeed
from .stall_characterization import StallCharacterizer
from .modes import mode_name
from .stall_test import (
    StallAttemptContext, StallAttemptResult, StallDepartureEvent,
    StallFlightResult, StallReason, StallResponseEvidence, StallRules,
    StallStatus, number, rows,
)


def _parameter(log, name, time_us):
    return number(log.parameter_history.value_at(name, time_us))


def _elevator_mapping(log, time_us):
    """Unique event-time SERVO function 19, limits and reversal."""
    channels = [channel for channel in range(1, 17)
                if _parameter(log, f"SERVO{channel}_FUNCTION", time_us) == 19]
    if len(channels) != 1:
        return None
    channel = channels[0]
    low = _parameter(log, f"SERVO{channel}_MIN", time_us)
    high = _parameter(log, f"SERVO{channel}_MAX", time_us)
    reverse = _parameter(log, f"SERVO{channel}_REVERSED", time_us)
    if low is None or high is None or reverse not in (0, 1) or high <= low:
        return None
    return channel, low, high, bool(reverse)


class StallAttemptAnalyzer:
    """Prototype evidence classifier; no stall-speed or recovery inference."""

    def __init__(self, config):
        self.rules = StallRules.from_config(config)
        self._log = None
        self._records = {}
        self._times = {}

    def _rows(self, log, source):
        if log is not self._log:
            self._log = log
            self._records = {}
            self._times = {}
        if source not in self._records:
            self._records[source] = rows(log, source)
            self._times[source] = [row.time_us for row in self._records[source]]
        return self._records[source]

    def _interval_rows(self, log, source, start_us, end_us):
        values = self._rows(log, source)
        times = self._times[source]
        return values[
            bisect_left(times, start_us):bisect_right(times, end_us)
        ]

    def _context(self, log, attempt, response):
        reference_us = response.pitch_peak.time_us if response else None
        if reference_us is None:
            speed_rows = [row for row in self._interval_rows(
                log, "ARSP", attempt.start_us, attempt.end_us,
            ) if usable_airspeed(row)]
            if speed_rows:
                reference_us = min(
                    speed_rows, key=lambda row: row.point("Airspeed").value,
                ).time_us
        aetr = self._interval_rows(
            log, "AETR", attempt.start_us,
            reference_us if reference_us is not None else attempt.end_us,
        )
        throttle = [number(row.values.get("Thr")) for row in aetr]
        throttle = [value for value in throttle if value is not None]
        flap = [number(row.values.get("Flap")) for row in aetr]
        flap = [value for value in flap if value is not None]
        throttle_value = median(throttle) if throttle else None
        reference_frame = next(
            (frame for frame in reversed(attempt.frames)
             if reference_us is not None
             and frame.time_us <= reference_us
             and reference_us - frame.time_us <= self.rules.association_max_us),
            None,
        )
        roll_value = (
            abs(reference_frame.roll.value)
            if reference_frame is not None and reference_frame.roll is not None
            else None
        )
        if throttle_value is None:
            throttle_class = "unknown"
        elif throttle_value <= self.rules.idle_throttle_percent:
            throttle_class = "idle_command"
        else:
            throttle_class = "powered_or_variable_command"
        if roll_value is None:
            bank_class = "unknown"
        elif roll_value <= self.rules.approximately_level_bank_deg:
            bank_class = "approximately_level"
        else:
            bank_class = "banked"
        flap_value = median(flap) if flap else None
        return StallAttemptContext(
            mode=mode_name(attempt.frames[0].mode),
            reference_us=reference_us,
            throttle_class=throttle_class,
            median_commanded_throttle_percent=throttle_value,
            bank_class=bank_class, abs_roll_at_reference_deg=roll_value,
            flap_command=flap_value,
            clean_idle_context=(
                attempt.frames[0].mode == 5
                and throttle_class == "idle_command"
                and bank_class == "approximately_level"
                and flap_value == 0
            ),
        )

    def _responses(self, attempt):
        rules = self.rules
        frames = attempt.frames
        responses = []
        for index, peak in enumerate(frames):
            if not peak.nose_up or peak.target is None:
                continue
            preceding = [frame for frame in frames[:index]
                         if peak.time_us - frame.time_us
                         <= rules.local_peak_lookback_us]
            if any(frame.pitch.value > (
                peak.pitch.value + rules.local_peak_tolerance_deg
            ) for frame in preceding):
                continue
            peak_error = peak.target.value - peak.pitch.value
            first_fall = None
            previous = peak
            for later in frames[index + 1:]:
                if later.time_us - peak.time_us > rules.fall_window_us:
                    break
                if later.time_us - previous.time_us > rules.attitude_max_gap_us:
                    break
                previous = later
                if not later.nose_up or later.target is None:
                    break
                if later.target.value < peak.target.value - rules.maximum_target_relax_deg:
                    break
                if (later.pilot_deflection_pwm is None
                    or peak.pilot_deflection_pwm is None
                    or later.pilot_deflection_pwm < (
                        peak.pilot_deflection_pwm - rules.maximum_input_relax_pwm
                    )):
                    break
                fall = peak.pitch.value - later.pitch.value
                growth = later.target.value - later.pitch.value - peak_error
                if later.pitch.value > (
                    peak.pitch.value + rules.local_peak_tolerance_deg
                ):
                    break
                if first_fall is None and fall > 0.5:
                    first_fall = later.pitch
                if (first_fall is not None
                    and fall >= rules.minimum_pitch_fall_deg
                    and growth >= rules.minimum_error_growth_deg):
                    responses.append(StallResponseEvidence(
                        pitch_peak=peak.pitch,
                        first_opposed_fall=first_fall,
                        confirmed_at=later.pitch,
                        target_at_peak=peak.target,
                        target_at_confirmation=later.target,
                        pilot_at_peak=peak.pilot,
                        pilot_at_confirmation=later.pilot,
                        pitch_fall_deg=fall,
                        error_growth_deg=growth,
                        peak_pilot_association_gap_us=(
                            peak.time_us - peak.pilot.time_us
                        ),
                        confirmation_pilot_association_gap_us=(
                            later.time_us - later.pilot.time_us
                        ),
                    ))
                    break
        return responses

    def _endpoints(self, log, response):
        rules = self.rules
        mapping = _elevator_mapping(log, response.pitch_peak.time_us)
        if mapping is None:
            return None, StallReason.MISSING_ELEVATOR_MAPPING
        channel, low, high, reversed_output = mapping
        beginning = response.pitch_peak.time_us - rules.endpoint_window_before_us
        ending = response.pitch_peak.time_us + rules.endpoint_window_after_us
        command_limit = rules.aetr_full_scale * (
            1 - rules.endpoint_nearness_fraction
        )
        command_rows = [
            row for row in self._interval_rows(log, "AETR", beginning, ending)
            if row.point("Elev") is not None
            and row.point("Elev").value >= command_limit
            and _elevator_mapping(log, row.time_us) == mapping
        ]
        if not command_rows:
            return None, StallReason.MISSING_COMMAND_ENDPOINT
        margin = (high - low) * rules.endpoint_nearness_fraction
        output_rows = []
        for row in self._interval_rows(log, "RCOU", beginning, ending):
            if _elevator_mapping(log, row.time_us) != mapping:
                continue
            output = row.point(f"C{channel}")
            if output is None:
                continue
            if (output.value <= low + margin if reversed_output
                else output.value >= high - margin):
                output_rows.append(row)
        if not output_rows:
            return None, StallReason.MISSING_OUTPUT_ENDPOINT
        pairs = [(aetr, rcou) for aetr in command_rows for rcou in output_rows
                 if abs(aetr.time_us - rcou.time_us) <= rules.association_max_us]
        if not pairs:
            return None, StallReason.EVIDENCE_GAP
        aetr, rcou = min(pairs, key=lambda pair: (
            abs(pair[0].time_us - pair[1].time_us), pair[0].time_us,
        ))
        return StallDepartureEvent(
            pitch_peak=response.pitch_peak,
            first_opposed_fall=response.first_opposed_fall,
            confirmed_at=response.confirmed_at,
            aetr_endpoint=aetr.point("Elev"),
            rcou_endpoint=rcou.point(f"C{channel}"),
            elevator_channel=channel,
            pitch_fall_deg=response.pitch_fall_deg,
            error_growth_deg=response.error_growth_deg,
            maximum_association_gap_us=abs(aetr.time_us - rcou.time_us),
        ), None

    def analyse(self, flight_log, attempt):
        reasons = list(attempt.preliminary_reasons)
        if not attempt.complete and attempt.end_reason not in reasons:
            reasons.append(attempt.end_reason)
        rejected = {
            StallReason.SHORT_MOVEMENT, StallReason.NO_SLOW_FLIGHT,
            StallReason.NOT_ARMED, StallReason.UNKNOWN_ARMED_STATE,
            StallReason.NOT_FBWA,
            StallReason.MISSING_PITCH_INPUT, StallReason.MISSING_TARGET,
        }
        if any(reason in rejected for reason in reasons):
            return StallAttemptResult(
                attempt, StallStatus.REJECTED, tuple(reasons),
                self._context(flight_log, attempt, None),
            )

        responses = self._responses(attempt)
        response = responses[0] if responses else None
        departure = None
        if responses:
            endpoint_reasons = []
            for candidate in responses:
                event, reason = self._endpoints(flight_log, candidate)
                if event is not None:
                    response = candidate
                    departure = event
                    break
                endpoint_reasons.append(reason)
            if departure is None:
                if (endpoint_reasons[0] is StallReason.MISSING_COMMAND_ENDPOINT
                    and self._has_command_endpoint(flight_log, attempt)):
                    reasons.append(StallReason.ENDPOINT_WITHOUT_FALL)
                else:
                    reasons.append(endpoint_reasons[0])
        else:
            if self._has_command_endpoint(flight_log, attempt):
                reasons.append(StallReason.ENDPOINT_WITHOUT_FALL)

        if any(reason in reasons for reason in (
            StallReason.MISSING_AIRSPEED, StallReason.UNHEALTHY_AIRSPEED,
            StallReason.EVIDENCE_GAP,
        )):
            status = StallStatus.AMBIGUOUS
        elif response is not None:
            status = (StallStatus.PROBABLE_DEPARTURE if departure is not None
                      else StallStatus.AMBIGUOUS)
        elif not attempt.complete or StallReason.ENDPOINT_WITHOUT_FALL in reasons:
            status = StallStatus.AMBIGUOUS
            if not attempt.complete:
                reasons.append(StallReason.TRUNCATED_DIVERGENCE)
        else:
            status = StallStatus.NO_DEMONSTRATED_DEPARTURE
            reasons.append(StallReason.NO_OPPOSED_FALL)
        if status is not StallStatus.PROBABLE_DEPARTURE:
            departure = None
        return StallAttemptResult(
            attempt=attempt, status=status,
            reasons=tuple(dict.fromkeys(reasons)),
            context=self._context(flight_log, attempt, response),
            response=response, departure=departure,
        )

    def _has_command_endpoint(self, log, attempt):
        limit = self.rules.aetr_full_scale * (
            1 - self.rules.endpoint_nearness_fraction
        )
        return any(
            row.point("Elev") is not None and row.point("Elev").value >= limit
            for row in self._interval_rows(
                log, "AETR", attempt.start_us, attempt.end_us,
            )
        )


class StallTestAnalyzer:
    """Analysis-only orchestration, independent of presentation and menu."""

    def __init__(self, config):
        self.extractor = StallAttemptExtractor(config)
        self.classifier = StallAttemptAnalyzer(config)

    def analyse(self, flight_log, flight_window):
        attempts = self.extractor.extract(flight_log, flight_window)
        classified = [self.classifier.analyse(flight_log, attempt)
                      for attempt in attempts]
        characterizer = StallCharacterizer(flight_log, self.extractor.rules)
        results = []
        for index, result in enumerate(classified):
            next_start = (classified[index + 1].attempt.start_us
                          if index + 1 < len(classified) else None)
            recovery = characterizer.recovery(
                result, flight_window.end_us, next_start,
            )
            results.append(replace(
                result, recovery=recovery,
                airspeed=characterizer.airspeed(result, recovery),
            ))
        return StallFlightResult(
            flight_window=flight_window,
            results=tuple(results),
            rule_version=self.extractor.rules.version,
            log_file=flight_log.metadata.get("log_file"),
            firmware_version=(flight_log.firmware_version() or {}).get("version"),
        )
