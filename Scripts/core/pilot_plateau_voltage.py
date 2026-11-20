"""Observed, read-only BAT plateau comparison for pilot-controlled launches."""

from dataclasses import dataclass
from itertools import pairwise
from statistics import median

import pandas as pd

from .battery_load_response import _invalid_near, _samples
from .pilot_battery_onset import PilotLoadOnset

PLATEAU_US = 1_000_000
MIN_DURATION_US = 800_000
MAX_GAP_US = 250_000
# A 1 ms allowance covers independently stamped 10 Hz BAT/T0 boundary jitter;
# the nominal evidence limit remains 0.5 s.
PRE_RECENCY_US = 501_000


@dataclass(frozen=True)
class ObservedPlateauVoltageComparison:
    status: str
    pre_start_us: int | None = None
    pre_end_us: int | None = None
    pre_voltage_v: float | None = None
    pre_current_a: float | None = None
    loaded_start_us: int | None = None
    loaded_end_us: int | None = None
    loaded_voltage_v: float | None = None
    loaded_current_a: float | None = None
    voltage_change_v: float | None = None
    current_change_a: float | None = None
    pre_to_t0_us: int | None = None
    t0_to_loaded_us: int | None = None


def _quality(rows, invalid, current_limit, voltage_limit, minimum_samples):
    if len(rows) < minimum_samples or rows[-1][0] - rows[0][0] < MIN_DURATION_US:
        return None
    if (_invalid_near(invalid, rows[0][0], rows[-1][0])
            or any(row[1] is None or row[2] is None for row in rows)
            or any(not 0 < b[0] - a[0] <= MAX_GAP_US
                   for a, b in pairwise(rows))):
        return None
    current = float(median(row[2] for row in rows))
    voltage = float(median(row[1] for row in rows))
    if (max(row[2] for row in rows) - min(row[2] for row in rows) > current_limit(current)
            or max(row[1] for row in rows) - min(row[1] for row in rows) > voltage_limit(voltage)):
        return None
    return voltage, current


def evaluate_observed_plateau_voltage(
    bat: pd.DataFrame, instance: int, onset: PilotLoadOnset, t1_us: int | None,
    flight_end_us: int,
) -> ObservedPlateauVoltageComparison:
    """Compare paired recorded plateaus; never infer sag or resistance."""
    if onset.t0_us is None or onset.launch_reference_a is None:
        return ObservedPlateauVoltageComparison("Pilot T0 or launch-current reference unavailable.")
    t0 = onset.t0_us
    rows, invalid = _samples(bat, instance)
    t0_rows = [row for row in rows if row[0] == t0]
    if (len(t0_rows) != 1 or t0_rows[0][1] is None or t0_rows[0][2] is None
            or _invalid_near(invalid, t0, t0)):
        return ObservedPlateauVoltageComparison("Missing or invalid BAT sample at T0.")
    prior = [row for row in rows if t0 - 2_000_000 <= row[0] < t0]
    if not prior or t0 - prior[-1][0] > PRE_RECENCY_US:
        return ObservedPlateauVoltageComparison("No sufficiently recent pre-onset plateau.")
    pre = None
    for end in reversed(range(len(prior))):
        if t0 - prior[end][0] > PRE_RECENCY_US:
            break
        interval = [row for row in prior if prior[end][0] - PLATEAU_US <= row[0] <= prior[end][0]]
        quality = _quality(interval, invalid, lambda value: max(0.5, 0.2 * value),
                           lambda value: max(0.15, 0.01 * value), 9)
        if quality is None:
            continue
        # An onset ramp may begin before the qualified T0 sample. Do not jump
        # over a gap, missing value, or a return below the candidate plateau.
        intervening = [row for row in prior if prior[end][0] < row[0] < t0]
        path = interval[-1:] + intervening + t0_rows
        if (any(row[1] is None or row[2] is None
                or row[2] < quality[1] - max(0.5, 0.2 * quality[1])
                for row in intervening)
                or any(not 0 < b[0] - a[0] <= MAX_GAP_US
                       for a, b in pairwise(path))
                or _invalid_near(invalid, prior[end][0], t0)):
            continue
        pre = (interval, quality)
        break
    if pre is None:
        recent = [row for row in prior if t0 - 1_500_000 <= row[0] < t0]
        if any(row[1] is None or row[2] is None for row in recent):
            return ObservedPlateauVoltageComparison("Missing current/voltage in pre-onset BAT evidence.")
        if (_invalid_near(invalid, t0 - 1_500_000, t0)
                or any(not 0 < b[0] - a[0] <= MAX_GAP_US
                       for a, b in pairwise(recent + t0_rows))):
            return ObservedPlateauVoltageComparison("BAT sampling gap or invalid timestamp before T0.")
        return ObservedPlateauVoltageComparison("No sufficiently recent pre-onset plateau.")
    limit = min(t0 + 6_000_000, t1_us if t1_us is not None else t0 + 6_000_000,
                flight_end_us)
    loaded_rows = [row for row in rows if t0 <= row[0] <= limit]
    if limit - t0 < MIN_DURATION_US or not loaded_rows:
        if flight_end_us - t0 < MIN_DURATION_US:
            return ObservedPlateauVoltageComparison("FlightWindow ends before a loaded plateau can qualify.")
        return ObservedPlateauVoltageComparison("No stable loaded plateau before T1.")
    loaded = None
    separated = False
    for start, row in enumerate(loaded_rows):
        interval = [item for item in loaded_rows[start:]
                    if item[0] <= row[0] + PLATEAU_US]
        quality = _quality(interval, invalid, lambda value: max(1.0, 0.15 * value),
                           lambda value: 0.18, 5)
        if quality is None:
            continue
        if quality[1] < max(pre[1][1] + 5.0, 0.7 * onset.launch_reference_a):
            separated = True
            continue
        through = [item for item in loaded_rows if item[0] <= interval[-1][0]]
        if any(item[1] is None or item[2] is None for item in through):
            return ObservedPlateauVoltageComparison("Missing current/voltage before loaded plateau.")
        if (_invalid_near(invalid, t0, interval[-1][0])
                or any(not 0 < b[0] - a[0] <= MAX_GAP_US for a, b in pairwise(through))):
            return ObservedPlateauVoltageComparison("BAT sampling gap or invalid timestamp before loaded plateau.")
        loaded = (interval, quality)
        break
    if loaded is None:
        reason = ("Insufficient current separation between plateaus." if separated else
                  "No stable loaded plateau before FlightWindow end." if flight_end_us < t0 + 6_000_000
                  and (t1_us is None or flight_end_us < t1_us) else
                  "No stable loaded plateau before T1." if t1_us is not None else
                  "No stable loaded plateau.")
        return ObservedPlateauVoltageComparison(reason)
    pre_rows, (pre_v, pre_i) = pre
    load_rows, (load_v, load_i) = loaded
    return ObservedPlateauVoltageComparison(
        "Qualified observed plateaus; comparison between stable observed load levels; "
        "not instantaneous sag or resistance.",
        pre_rows[0][0], pre_rows[-1][0], pre_v, pre_i,
        load_rows[0][0], load_rows[-1][0], load_v, load_i,
        pre_v - load_v, load_i - pre_i, t0 - pre_rows[-1][0], load_rows[0][0] - t0,
    )
