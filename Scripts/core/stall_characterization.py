"""Stall-local native-time airspeed provenance and recovery observations."""

from bisect import bisect_left

from .stall_test import (
    AirspeedMeasurement, AirspeedQuality, SavedAirspeedParameters,
    StallAirspeedEvidence, StallRecovery, number, rows,
)


_SAVED_AIRSPEED_NAMES = (
    "ARSPD_RATIO", "ARSPD_OFFSET", "ARSPD_AUTOCAL", "ARSPD_TYPE",
    "ARSPD_USE", "ARSPD_PRIMARY", "ARSPD_TUBE_ORDR", "ARSPD_OPTIONS",
    "ARSPD_DEVID", "ARSPD2_TYPE", "ARSPD_WIND_GATE", "ARSPD_WIND_WARN",
    "ARSPD_WIND_MAX", "AIRSPEED_STALL", "AIRSPEED_MIN",
)
_MATCHED_FIRMWARE = "ArduPlane V4.7.0 (1511f271)"
_RATIO_FORMULA = "ARSP.Airspeed**2 / ARSP.DiffPress (corrected pressure)"


class StallCharacterizer:
    """Enrich a classified attempt without changing its detector outcome."""

    def __init__(self, log, rules):
        self.log = log
        self.rules = rules
        self._rows = {}
        self._times = {}

    def _source(self, name):
        if name not in self._rows:
            self._rows[name] = rows(self.log, name)
            self._times[name] = [row.time_us for row in self._rows[name]]
        return self._rows[name]

    def _between(self, name, start_us, end_us):
        series = self._source(name)
        times = self._times[name]
        return series[bisect_left(times, start_us):bisect_left(times, end_us + 1)]

    def _nearest(self, name, reference_us, max_gap_us=None):
        series = self._source(name)
        if not series:
            return None
        index = bisect_left(self._times[name], reference_us)
        candidates = series[max(0, index - 1):min(len(series), index + 1)]
        chosen = min(candidates, key=lambda row: (
            abs(row.time_us - reference_us), row.time_us,
        ))
        limit = self.rules.association_max_us if max_gap_us is None else max_gap_us
        return chosen if abs(chosen.time_us - reference_us) <= limit else None

    def _parameter(self, name, time_us):
        return number(self.log.parameter_history.value_at(name, time_us))

    def _saved(self, reference_us):
        return SavedAirspeedParameters(
            reference_us,
            {name: self._parameter(name, reference_us)
             for name in _SAVED_AIRSPEED_NAMES},
        )

    def _quality(self, row):
        if row is None:
            return AirspeedQuality.UNAVAILABLE, ("no ARSP row within association limit",)
        reasons = []
        speed = number(row.values.get("Airspeed"))
        pressure = number(row.values.get("DiffPress"))
        sensor = number(row.values.get("I"))
        primary = number(row.values.get("Pri"))
        if speed is None or speed <= 0:
            reasons.append("missing or non-positive raw airspeed")
        if pressure is None or pressure <= 0:
            reasons.append("missing or non-positive corrected differential pressure")
        if sensor is None or primary is None or sensor != primary:
            reasons.append("primary sensor instance unknown or mismatched")
        if number(row.values.get("H")) != 1:
            reasons.append("sensor not logged healthy")
        if number(row.values.get("U")) != 1:
            reasons.append("sensor not logged in use")
        hp = number(row.values.get("Hp"))
        if hp is not None and hp < self.rules.airspeed_health_probability_min:
            reasons.append("low logged health probability")
        tr = number(row.values.get("TR"))
        gate = self._parameter("ARSPD_WIND_GATE", row.time_us)
        if tr is not None and gate is not None and tr > gate:
            reasons.append("logged consistency ratio exceeds configured gate")
        if speed is not None and speed > 0:
            series = self._source("ARSP")
            index = bisect_left(self._times["ARSP"], row.time_us)
            before = series[index - 1] if index else None
            after = series[index + 1] if index + 1 < len(series) else None
            if (before is not None and after is not None
                and number(before.values.get("I")) == sensor
                and number(after.values.get("I")) == sensor
                and row.time_us - before.time_us <= self.rules.airspeed_max_gap_us
                and after.time_us - row.time_us <= self.rules.airspeed_max_gap_us):
                adjacent = [number(other.values.get("Airspeed"))
                            for other in (before, after)]
                if all(value is not None and value > 0 for value in adjacent):
                    factor = self.rules.airspeed_excursion_factor
                    if (all(value > factor * speed for value in adjacent)
                        or all(speed > factor * value for value in adjacent)):
                        reasons.append("isolated abrupt airspeed excursion")
        return (AirspeedQuality.SUSPECT if reasons else AirspeedQuality.USABLE,
                tuple(reasons))

    def _measurement(self, reference_us, row=None):
        if row is None:
            candidates = self._between(
                "ARSP", reference_us - self.rules.association_max_us,
                reference_us + self.rules.association_max_us,
            )
            primary = [candidate for candidate in candidates
                       if number(candidate.values.get("I")) is not None
                       and number(candidate.values.get("I"))
                       == number(candidate.values.get("Pri"))]
            pool = primary or candidates
            row = min(pool, key=lambda item: (
                abs(item.time_us - reference_us), item.time_us,
            ), default=None)
        quality, warnings = self._quality(row)
        saved = self._saved(reference_us)
        if row is None:
            return AirspeedMeasurement(
                reference_us, None, None, None, None, quality, warnings,
                saved_parameters=saved,
            )
        sensor = number(row.values.get("I"))
        primary = number(row.values.get("Pri"))
        sensor_id = int(sensor) if sensor is not None and sensor.is_integer() else None
        primary_id = int(primary) if primary is not None and primary.is_integer() else None
        ratio = None
        formula = None
        version = self.log.firmware_version()
        saved_at_sample = self._saved(row.time_us)
        params = saved_at_sample.values
        if quality is AirspeedQuality.USABLE:
            if (version is not None
                and version["version"] == _MATCHED_FIRMWARE
                and sensor_id == primary_id == 0
                and params["ARSPD_PRIMARY"] == 0
                and params["ARSPD_TYPE"] == 9
                and params["ARSPD_TUBE_ORDR"] == 2
                and params["ARSPD_USE"] == 1):
                ratio = row.point("Airspeed").value ** 2 / row.point("DiffPress").value
                formula = _RATIO_FORMULA
            else:
                warnings += ("effective ratio unsupported for firmware/sensor configuration",)
        return AirspeedMeasurement(
            reference_us=reference_us, sample=row.point("Airspeed"),
            association_gap_us=abs(row.time_us - reference_us),
            sensor_instance=sensor_id, primary_instance=primary_id,
            quality=quality, warnings=warnings,
            corrected_diff_pressure=row.point("DiffPress"),
            logged_offset=row.point("Offset"), health=row.point("H"),
            in_use=row.point("U"), health_probability=row.point("Hp"),
            consistency_ratio=row.point("TR"), saved_parameters=saved,
            saved_parameters_at_sample=saved_at_sample,
            effective_ratio=ratio, effective_ratio_formula=formula,
        )

    def _minimum(self, attempt):
        candidates = [row for row in self._between(
            "ARSP", attempt.start_us, attempt.end_us,
        ) if self._quality(row)[0] is AirspeedQuality.USABLE]
        if not candidates:
            return None
        row = min(candidates, key=lambda item: (
            item.point("Airspeed").value, item.time_us,
        ))
        return self._measurement(row.time_us, row)

    def _selected_at_peak(self, reference_us):
        row = self._nearest("CTUN", reference_us)
        return ((row.point("As"), row.point("AsT")) if row else (None, None))

    def airspeed(self, result, recovery):
        response = result.response
        peak = response.pitch_peak.time_us if response else None
        selected, selected_source = self._selected_at_peak(peak) if peak else (None, None)
        return StallAirspeedEvidence(
            raw_airspeed_at_pre_fall_pitch_peak=(
                self._measurement(peak) if peak is not None else None
            ),
            raw_airspeed_at_first_opposed_fall_observation=(
                self._measurement(response.first_opposed_fall.time_us)
                if response else None
            ),
            lowest_usable_raw_airspeed_in_attempt=self._minimum(result.attempt),
            raw_airspeed_at_recovery_start=(
                self._measurement(recovery.control_start.time_us)
                if recovery else None
            ),
            raw_airspeed_at_observed_recovery_milestone=(
                self._measurement(recovery.first_sustained_airspeed_increase.time_us)
                if recovery and recovery.first_sustained_airspeed_increase else None
            ),
            selected_ctun_airspeed_at_peak=selected,
            selected_ctun_source_at_peak=selected_source,
        )

    def _sustained_speed_increase(self, start_us, end_us):
        usable = [row for row in self._between("ARSP", start_us, end_us)
                  if self._quality(row)[0] is AirspeedQuality.USABLE]
        for first, middle, last in zip(usable, usable[1:], usable[2:]):
            if (middle.time_us - first.time_us <= self.rules.airspeed_max_gap_us
                and last.time_us - middle.time_us <= self.rules.airspeed_max_gap_us
                and first.point("Airspeed").value <= middle.point("Airspeed").value
                <= last.point("Airspeed").value
                and last.point("Airspeed").value
                - first.point("Airspeed").value
                >= self.rules.recovery_speed_increase_m_s):
                return last.point("Airspeed")
        return None

    def recovery(self, result, flight_end_us, next_start_us=None):
        if result.departure is None:
            return None
        attempt = result.attempt
        reference_us = result.departure.pitch_peak.time_us
        horizon = min(flight_end_us,
                      attempt.end_us + self.rules.recovery_followup_us)
        if not attempt.complete:
            horizon = min(horizon, attempt.end_us)
        if next_start_us is not None:
            horizon = min(horizon, next_start_us - 1)
        confirmed_us = result.departure.confirmed_at.time_us
        response = result.response
        pilot_high = next(
            (frame.pilot_deflection_pwm for frame in attempt.frames
             if frame.time_us == confirmed_us), None,
        )
        target_high = response.target_at_confirmation.value
        pilot = target = None
        for frame in attempt.frames:
            if frame.time_us <= confirmed_us:
                continue
            if frame.pilot is not None and frame.pilot_deflection_pwm is not None:
                pilot_high = max(pilot_high or 0, frame.pilot_deflection_pwm)
                if (pilot is None and pilot_high - frame.pilot_deflection_pwm
                    > self.rules.maximum_input_relax_pwm):
                    pilot = frame.pilot
            if frame.target is not None:
                target_high = max(target_high, frame.target.value)
                if (target is None and target_high - frame.target.value
                    > self.rules.maximum_target_relax_deg):
                    target = frame.target
        power_rows = self._between("AETR", attempt.start_us, confirmed_us)
        baseline = [row.point("Thr").value for row in power_rows
                    if row.point("Thr") is not None]
        power = None
        if baseline:
            base = sorted(baseline)[len(baseline) // 2]
            for row in self._between("AETR", confirmed_us + 1, horizon):
                point = row.point("Thr")
                if (point is not None and point.value
                    >= base + self.rules.recovery_power_increase_percent):
                    power = point
                    break
        controls = [item for item in (pilot, target, power) if item is not None]
        if not controls:
            return None
        control_start = min(controls, key=lambda point: point.time_us)
        pitch_rows = self._between("ATT", control_start.time_us, horizon)
        pitch_min_row = min(
            (row for row in pitch_rows if row.point("Pitch") is not None),
            key=lambda row: row.point("Pitch").value, default=None,
        )
        pitch_min = pitch_min_row.point("Pitch") if pitch_min_row else None
        target_min = pitch_min_row.point("DesPitch") if pitch_min_row else None
        limit = self._parameter("PTCH_LIM_MIN_DEG", pitch_min.time_us) if pitch_min else None
        below_limit = pitch_min.value < limit if pitch_min and limit is not None else None
        command = output = None
        if pitch_min is not None:
            aetr = self._nearest("AETR", pitch_min.time_us)
            rcou = self._nearest("RCOU", pitch_min.time_us)
            channel = result.departure.elevator_channel
            if aetr and rcou:
                candidate = aetr.point("Elev")
                pwm = rcou.point(f"C{channel}")
                low = self._parameter(f"SERVO{channel}_MIN", pitch_min.time_us)
                high = self._parameter(f"SERVO{channel}_MAX", pitch_min.time_us)
                reversed_output = self._parameter(
                    f"SERVO{channel}_REVERSED", pitch_min.time_us,
                )
                mapped_channels = [candidate_channel for candidate_channel in
                                   range(1, 17) if self._parameter(
                                       f"SERVO{candidate_channel}_FUNCTION",
                                       pitch_min.time_us,
                                   ) == 19]
                if (candidate is not None and candidate.value > 0
                    and pwm is not None and low is not None and high is not None
                    and mapped_channels == [channel]
                    and reversed_output in (0, 1)
                    and ((pwm.value < (low + high) / 2) if reversed_output
                         else (pwm.value > (low + high) / 2))):
                    command, output = candidate, pwm
        baro_rows = self._between("BARO", reference_us, horizon)
        departure_baro = self._nearest("BARO", reference_us)
        recovery_baro = self._nearest("BARO", control_start.time_us)
        def healthy_baro(row):
            return row is not None and number(row.values.get("H")) in (None, 1)

        if not healthy_baro(departure_baro):
            departure_baro = None
        if not healthy_baro(recovery_baro):
            recovery_baro = None
        baro_rows = [row for row in baro_rows if healthy_baro(row)]
        anchor = departure_baro or recovery_baro
        if anchor is not None and number(anchor.values.get("I")) is not None:
            instance = number(anchor.values.get("I"))
            baro_rows = [row for row in baro_rows
                         if number(row.values.get("I")) == instance]
            if (recovery_baro is not None
                and number(recovery_baro.values.get("I")) != instance):
                recovery_baro = min(
                    baro_rows,
                    key=lambda row: abs(row.time_us - control_start.time_us),
                    default=None,
                )
                if (recovery_baro is not None
                    and abs(recovery_baro.time_us - control_start.time_us)
                    > self.rules.association_max_us):
                    recovery_baro = None
        low_row = min(
            (row for row in baro_rows if row.point("Alt") is not None),
            key=lambda row: row.point("Alt").value, default=None,
        )
        low = low_row.point("Alt") if low_row else None
        dep_alt = departure_baro.point("Alt") if departure_baro else None
        recovery_alt = recovery_baro.point("Alt") if recovery_baro else None
        sink_arrest = None
        prior = None
        for row in baro_rows:
            rate = row.point("CRt")
            if rate is None:
                continue
            if (row.time_us >= control_start.time_us and prior is not None
                and prior.value < 0 <= rate.value
                and row.time_us - prior.time_us <= 500_000):
                sink_arrest = rate
                break
            prior = rate
        return StallRecovery(
            control_start=control_start, pilot_demand_reduction=pilot,
            target_reduction=target, commanded_power_increase=power,
            pitch_minimum=pitch_min, target_at_pitch_minimum=target_min,
            pitch_limit_min_deg=limit, attitude_below_target_limit=below_limit,
            nose_up_elevator_command=command,
            nose_up_elevator_pwm_command=output,
            first_sustained_airspeed_increase=self._sustained_speed_increase(
                control_start.time_us, horizon,
            ),
            sink_arrest=sink_arrest,
            altitude_at_departure_reference=dep_alt,
            altitude_at_recovery_start=recovery_alt,
            lowest_altitude_after_departure=low,
            altitude_loss_from_departure_reference_m=(
                max(0, dep_alt.value - low.value) if dep_alt and low else None
            ),
            altitude_loss_from_recovery_start_m=(
                max(0, recovery_alt.value - low.value)
                if recovery_alt and low else None
            ),
        )
