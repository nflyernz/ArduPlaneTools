"""Segment FBWA slow-flight pulls without depending on departure outcome."""

from .stall_test import (
    RowIndex, StallAttempt, StallFrame, StallReason, StallRules, number, rows,
)


def _parameter(log, name, time_us):
    return number(log.parameter_history.value_at(name, time_us))


def usable_airspeed(row):
    """Minimal same-row ARSP screening; calibration provenance comes later."""
    speed = number(row.values.get("Airspeed"))
    pressure = number(row.values.get("DiffPress"))
    sensor = number(row.values.get("I"))
    primary = number(row.values.get("Pri"))
    healthy = number(row.values.get("H"))
    in_use = number(row.values.get("U"))
    return (
        speed is not None and speed > 0
        and pressure is not None and pressure > 0
        and sensor is not None and primary is not None and sensor == primary
        and healthy == 1 and in_use == 1
    )


def _pull_confirmation(frames, minimum_us):
    """First native row that completes one uninterrupted nose-up run."""
    run_start = None
    for frame in frames:
        if not frame.nose_up:
            run_start = None
        elif run_start is None:
            run_start = frame.time_us
        elif frame.time_us - run_start >= minimum_us:
            return frame.time_us
    return None


class StallAttemptExtractor:
    """Preserve candidate, negative and incomplete pulls within one flight."""

    def __init__(self, config):
        self.rules = StallRules.from_config(config)

    def _frames(self, log, window):
        rules = self.rules
        rcin = RowIndex(rows(log, "RCIN"))
        modes = RowIndex(rows(log, "MODE"))
        arm = RowIndex(rows(log, "ARM"))
        stat = RowIndex(rows(log, "STAT"))
        result = []
        for attitude in rows(log, "ATT"):
            if not window.start_us <= attitude.time_us <= window.end_us:
                continue
            pitch = attitude.point("Pitch")
            if pitch is None:
                continue
            target = attitude.point("DesPitch")
            roll = attitude.point("Roll")
            mode_row = modes.before(attitude.time_us, attitude.source_order)
            mode = None
            if mode_row is not None:
                mode = number(mode_row.values.get(
                    "ModeNum", mode_row.values.get("Mode")
                ))
            arm_row = arm.before(attitude.time_us, attitude.source_order)
            stat_row = stat.before(attitude.time_us, attitude.source_order)
            armed = None
            if arm_row is not None:
                state = number(arm_row.values.get("ArmState"))
                if state is not None:
                    armed = state == 1
            if stat_row is not None:
                state = number(stat_row.values.get("Armed"))
                if state is not None:
                    stat_armed = state == 1
                    armed = stat_armed if armed is None or armed == stat_armed else None

            rc_row = rcin.before(
                attitude.time_us, attitude.source_order,
                rules.association_max_us,
            )
            pilot = None
            deflection = None
            channel = _parameter(log, "RCMAP_PITCH", attitude.time_us)
            if rc_row is not None and channel is not None and 1 <= channel <= 16:
                channel = int(channel)
                pilot = rc_row.point(f"C{channel}")
                trim = _parameter(log, f"RC{channel}_TRIM", attitude.time_us)
                if pilot is not None and trim is not None:
                    reversed_value = _parameter(
                        log, f"RC{channel}_REVERSED", attitude.time_us
                    )
                    sign = -1 if reversed_value == 1 else 1
                    deflection = sign * (pilot.value - trim)

            result.append(StallFrame(
                pitch=pitch,
                target=target,
                roll=roll,
                pilot=pilot,
                pilot_deflection_pwm=deflection,
                target_nose_up=(
                    target is not None
                    and target.value >= rules.nose_up_target_deg
                ),
                pilot_nose_up=(
                    deflection is not None
                    and deflection >= rules.nose_up_input_pwm
                ),
                mode=int(mode) if mode is not None else None,
                armed=armed,
            ))
        return result

    def _preliminary_reasons(self, speed_rows, frames, start_us, end_us):
        rules = self.rules
        reasons = []
        if _pull_confirmation(frames, rules.minimum_pull_us) is None:
            reasons.append(StallReason.SHORT_MOVEMENT)
        if all(frame.target is None for frame in frames):
            reasons.append(StallReason.MISSING_TARGET)
        if all(frame.pilot_deflection_pwm is None for frame in frames):
            reasons.append(StallReason.MISSING_PITCH_INPUT)
        if any(frame.armed is False for frame in frames):
            reasons.append(StallReason.NOT_ARMED)
        if any(frame.armed is None for frame in frames):
            reasons.append(StallReason.UNKNOWN_ARMED_STATE)
        if any(frame.mode != 5 for frame in frames):
            reasons.append(StallReason.NOT_FBWA)

        speed_rows = [row for row in speed_rows
                      if start_us - rules.speed_lookback_us <= row.time_us <= end_us]
        primary = [row for row in speed_rows if usable_airspeed(row)]
        within = [row for row in primary if start_us <= row.time_us <= end_us]
        if not speed_rows:
            reasons.append(StallReason.MISSING_AIRSPEED)
        elif len(within) < 3:
            reasons.append(StallReason.UNHEALTHY_AIRSPEED)
        else:
            times = [row.time_us for row in within]
            if any(b - a > rules.airspeed_max_gap_us
                   for a, b in zip(times, times[1:])):
                reasons.append(StallReason.EVIDENCE_GAP)
            early = [row for row in primary
                     if row.time_us <= start_us + rules.speed_lookback_us]
            if early:
                peak = max(row.point("Airspeed").value for row in early)
                low = min(row.point("Airspeed").value for row in within)
                if peak - low < rules.minimum_relative_speed_drop_m_s:
                    reasons.append(StallReason.NO_SLOW_FLIGHT)
            else:
                reasons.append(StallReason.NO_SLOW_FLIGHT)
        return tuple(dict.fromkeys(reasons))

    def extract(self, flight_log, flight_window):
        frames = self._frames(flight_log, flight_window)
        if not frames:
            return []
        speed_rows = rows(flight_log, "ARSP")
        rules = self.rules
        attempts = []
        active = []
        release_at = None
        partial_reset_at = None
        high_pilot = 0.0
        high_target = 0.0
        reapply_from = None
        for frame in frames:
            if active:
                previous = active[-1]
                if frame.time_us - previous.time_us > rules.attitude_max_gap_us:
                    attempts.append(self._close(
                        speed_rows, active, previous.time_us,
                        StallReason.EVIDENCE_GAP, False,
                    ))
                    active = []
                    release_at = None
                    partial_reset_at = None
                elif frame.mode != previous.mode or (
                    previous.armed is True and frame.armed is not True
                ):
                    reason = (StallReason.MODE_BOUNDARY
                              if frame.mode != previous.mode
                              else StallReason.NOT_ARMED)
                    attempts.append(self._close(
                        speed_rows, active, frame.time_us, reason, False,
                    ))
                    active = []
                    release_at = None
                    partial_reset_at = None
            if not active:
                if reapply_from is not None:
                    pilot_low, target_low = reapply_from
                    if (frame.pilot_deflection_pwm is None
                        or frame.target is None
                        or frame.pilot_deflection_pwm < (
                            pilot_low + rules.reapply_input_rise_pwm
                        )
                        or frame.target.value < (
                            target_low + rules.reapply_target_rise_deg
                        )):
                        continue
                    reapply_from = None
                # A single missing demand stream is retained as a diagnostic.
                candidate = (
                    frame.demand_up
                    or (frame.target is None and frame.pilot_nose_up)
                    or (frame.pilot is None and frame.target_nose_up)
                )
                if candidate:
                    active = [frame]
                    high_pilot = frame.pilot_deflection_pwm or 0.0
                    high_target = frame.target.value if frame.target else 0.0
                continue
            active.append(frame)
            high_pilot = max(high_pilot, frame.pilot_deflection_pwm or 0.0)
            high_target = max(
                high_target, frame.target.value if frame.target else 0.0,
            )
            partial_reset = (
                frame.pilot_deflection_pwm is not None
                and frame.target is not None
                and high_pilot >= 2 * rules.nose_up_input_pwm
                and high_target >= 2 * rules.nose_up_target_deg
                and frame.pilot_deflection_pwm <= (
                    high_pilot * rules.partial_reset_fraction
                )
                and frame.target.value <= (
                    high_target * rules.partial_reset_fraction
                )
            )
            if partial_reset:
                if partial_reset_at is None:
                    partial_reset_at = frame.time_us
                if frame.time_us - partial_reset_at >= rules.partial_reset_us:
                    attempts.append(self._close(
                        speed_rows, active, frame.time_us,
                        StallReason.PILOT_RELEASE, True,
                    ))
                    reapply_from = (
                        frame.pilot_deflection_pwm, frame.target.value,
                    )
                    active = []
                    release_at = None
                    partial_reset_at = None
                    continue
            else:
                partial_reset_at = None
            evidence_demand_up = (
                frame.demand_up
                or (frame.target is None and frame.pilot_nose_up)
                or (frame.pilot is None and frame.target_nose_up)
            )
            if evidence_demand_up:
                release_at = None
            else:
                if release_at is None:
                    release_at = frame.time_us
                if frame.time_us - release_at >= rules.release_reset_us:
                    attempts.append(self._close(
                        speed_rows, active, frame.time_us,
                        StallReason.PILOT_RELEASE, True,
                    ))
                    active = []
                    release_at = None
                    partial_reset_at = None

        if active:
            attempts.append(self._close(
                speed_rows, active, flight_window.end_us,
                StallReason.FLIGHT_BOUNDARY, False,
            ))
        return attempts

    def _close(self, speed_rows, frames, end_us, reason, complete):
        start_us = frames[0].time_us
        preliminary = self._preliminary_reasons(
            speed_rows, frames, start_us, end_us,
        )
        confirmed = _pull_confirmation(frames, self.rules.minimum_pull_us)
        return StallAttempt(
            start_us=start_us, confirmed_us=confirmed, end_us=end_us,
            end_reason=reason, complete=complete, frames=tuple(frames),
            preliminary_reasons=preliminary,
        )
