"""Pilot-specific, read-only BAT onset evidence and GPS-anchored observations.

The AUTO onset and shared load-response evaluator are deliberately separate.
An onset is the earliest sustained load rise associated with launch throttle
that has a recent stable BAT baseline. Voltage is never used to rank onsets.
"""

from dataclasses import dataclass
from itertools import pairwise
from statistics import median

import pandas as pd

from .battery_load_response import GAP_US, _invalid_near, _samples, _smoothed

BASELINE_US = 1_000_000
CONFIRM_US = 800_000


@dataclass(frozen=True)
class PilotLoadOnset:
    t0_us: int | None
    status: str
    baseline_start_us: int | None = None
    baseline_end_us: int | None = None
    baseline_current_a: float | None = None
    baseline_voltage_v: float | None = None
    onset_threshold_a: float | None = None
    confirmed_current_a: float | None = None
    confirmation_end_us: int | None = None
    throttle_pct: float | None = None
    launch_reference_a: float | None = None


@dataclass(frozen=True)
class GpsAnchoredBatteryObservation:
    start_us: int
    end_us: int
    raw_peak_current_a: float | None
    minimum_voltage_v: float | None
    current_at_minimum_a: float | None
    status: str


def _continuous(rows):
    return bool(rows) and all(0 < later[0] - earlier[0] <= GAP_US
                              for earlier, later in pairwise(rows))


def _throttle_rows(frame):
    if frame is None or frame.empty or not {"TimeUS", "ThO"}.issubset(frame.columns):
        return []
    data = frame[["TimeUS", "ThO"]].apply(pd.to_numeric, errors="coerce").dropna()
    return [(int(stamp), float(value)) for stamp, value in data.itertuples(index=False, name=None)
            if stamp >= 0 and stamp == int(stamp)]


def _stable_baseline(rows, candidate_index, invalid_intervals):
    """Find the nearest complete one-second BAT plateau before a candidate."""
    stamp = rows[candidate_index][0]
    for endpoint in reversed(rows[:candidate_index]):
        if endpoint[0] > stamp - 200_000:
            continue
        if endpoint[0] < stamp - 3_000_000:
            break
        segment = [row for row in rows
                   if endpoint[0] - BASELINE_US <= row[0] <= endpoint[0]]
        if (len(segment) < 8 or segment[-1][0] - segment[0][0] < 900_000
                or not _continuous(segment)
                or _invalid_near(invalid_intervals, segment[0][0], stamp)
                or any(row[1] is None or row[2] is None for row in segment)):
            continue
        current = float(median(row[2] for row in segment))
        voltage = float(median(row[1] for row in segment))
        if (current <= 0
                or max(row[2] for row in segment) - min(row[2] for row in segment)
                > max(0.5, 0.2 * current)
                or max(row[1] for row in segment) - min(row[1] for row in segment)
                > max(0.15, 0.01 * voltage)):
            continue
        return segment[0][0], segment[-1][0], current, voltage
    return None


def detect_pilot_load_onset(
    bat: pd.DataFrame, instance: int, transition_us: int, throttle: pd.DataFrame
) -> PilotLoadOnset:
    """Qualify the earliest sustained, throttle-associated pilot load stage.

    BAT is searched from eight seconds before to four seconds after the GPS
    transition. Three more seconds before that supply baseline evidence.
    The launch-current reference only rejects small taxi stages; it does not
    choose an onset or alter the shared T1 reference definition.
    """
    rows, invalid_intervals = _samples(bat, instance)
    rows = [row for row in rows
            if transition_us - 11_000_000 <= row[0] <= transition_us + 6_000_000]
    launch = [row for row in rows
              if transition_us <= row[0] <= transition_us + 6_000_000]
    if (len(launch) < 20 or not _continuous(launch)
            or any(row[2] is None for row in launch)
            or _invalid_near(invalid_intervals, transition_us, transition_us + 6_000_000)):
        return PilotLoadOnset(None, "Pilot BAT onset unavailable: launch current is incomplete.")
    smooth = [value for value in _smoothed(launch) if value is not None]
    if len(smooth) < 10:
        return PilotLoadOnset(None, "Pilot BAT onset unavailable: smoothed launch current is incomplete.")
    reference = float(pd.Series(smooth).quantile(0.9))
    # A quarter-reference taxi stage can be sustained for several seconds;
    # require a material share of the launch load before naming T0.
    minimum_stage = max(2.0, 0.4 * reference)
    throttle_rows = _throttle_rows(throttle)
    for index, row in enumerate(rows):
        stamp, _, current = row
        if stamp < transition_us - 8_000_000 or stamp > transition_us + 4_000_000:
            continue
        if current is None or current < minimum_stage:
            continue
        baseline = _stable_baseline(rows, index, invalid_intervals)
        if baseline is None:
            continue
        baseline_start, baseline_end, baseline_current, baseline_voltage = baseline
        threshold = baseline_current + max(0.8, 0.2 * baseline_current)
        if current < threshold:
            continue
        previous = rows[index - 1] if index else None
        if (previous is None or previous[2] is None
                or previous[2] >= threshold and previous[2] >= minimum_stage):
            continue
        follow = [item for item in rows
                  if stamp <= item[0] <= stamp + CONFIRM_US]
        if (len(follow) < 5 or follow[-1][0] - stamp < 500_000
                or not _continuous(follow)
                or any(item[2] is None for item in follow)
                or _invalid_near(invalid_intervals, baseline_start, follow[-1][0])):
            continue
        confirmed = float(median(item[2] for item in follow))
        if confirmed < threshold or sum(item[2] >= threshold for item in follow) < 4:
            continue
        # Allow 0.2 s for BAT/CTUN timestamp skew, while requiring propulsion
        # demand to continue into the current-rise confirmation interval.
        power = [(time, value) for time, value in throttle_rows
                 if stamp - 200_000 <= time <= stamp + CONFIRM_US and value >= 20]
        if len(power) < 3 or power[-1][0] - power[0][0] < 200_000:
            continue
        return PilotLoadOnset(
            stamp, "Qualified pilot BAT load rise with stable prior current, "
            "sustained follow-through and launch throttle.",
            baseline_start, baseline_end, baseline_current, baseline_voltage,
            threshold, confirmed, follow[-1][0], max(value for _, value in power), reference,
        )
    return PilotLoadOnset(
        None, "Pilot BAT onset unavailable: no sustained launch-associated rise "
        "with a stable preceding BAT baseline.", launch_reference_a=reference,
    )


def observe_gps_anchored_bat(
    bat: pd.DataFrame, instance: int, transition_us: int, end_us: int
) -> GpsAnchoredBatteryObservation | None:
    """Return observed extrema without T0, sag or recovery semantics."""
    rows, invalid_intervals = _samples(bat, instance)
    rows = [row for row in rows
            if transition_us <= row[0] <= min(transition_us + 20_000_000, end_us)]
    if not rows:
        return None
    currents = [row[2] for row in rows if row[2] is not None]
    voltage_rows = [row for row in rows if row[1] is not None]
    minimum = min(voltage_rows, key=lambda row: row[1]) if voltage_rows else None
    complete = (_continuous(rows)
                and not _invalid_near(invalid_intervals, rows[0][0], rows[-1][0])
                and all(row[1] is not None and row[2] is not None for row in rows))
    status = ("GPS-anchored observed BAT samples; no T0, sag, T1 or recovery inferred."
              if complete else
              "GPS-anchored BAT samples have gaps, invalid timestamps or missing "
              "voltage/current values; extrema are partial observations only. "
              "No T0, sag, T1 or recovery inferred.")
    return GpsAnchoredBatteryObservation(
        rows[0][0], rows[-1][0], max(currents) if currents else None,
        minimum[1] if minimum else None,
        minimum[2] if minimum else None, status,
    )
