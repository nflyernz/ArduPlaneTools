"""Read-only BAT load response. Times and measurements come from recorded samples.

The 90th-percentile reference uses trailing 0.5 s medians with at least three
samples. Unlike the exploratory liftoff-anchored replay, an explicit T0 anchors
the first six seconds; callers must establish T0 independently.
"""

import math
from dataclasses import dataclass
from statistics import median

import pandas as pd

HORIZON_US = 20_000_000
GAP_US = 400_000
SMOOTH_US = 500_000
CONFIRM_US = 3_000_000


@dataclass(frozen=True)
class BatteryLoadResponse:
    t0_us: int | None
    t1_us: int | None
    reference_current_a: float | None
    threshold_current_a: float | None
    raw_peak_current_a: float | None
    baseline_voltage_v: float | None
    baseline_current_a: float | None
    minimum_voltage_v: float | None
    current_at_minimum_a: float | None
    voltage_drop_v: float | None
    follow_up_time_us: int | None
    follow_up_voltage_v: float | None
    follow_up_current_a: float | None
    observation_end_us: int | None
    status: str
    gaps: bool = False
    reaccelerated: bool = False


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _samples(bat: pd.DataFrame, instance: int):
    """Keep logged order so invalid or reversed timestamps cannot be hidden."""
    if bat is None or bat.empty or not {"TimeUS", "Inst"}.issubset(bat.columns):
        return [], []
    rows = []
    invalid_intervals = []
    invalid_after = None
    pending_invalid = False
    for row in bat.itertuples(index=False):
        if _number(row.Inst) != instance:
            continue
        stamp = _number(row.TimeUS)
        if stamp is None or stamp < 0 or not stamp.is_integer():
            if not pending_invalid:
                invalid_after = rows[-1][0] if rows else None
            pending_invalid = True
            continue
        if pending_invalid:
            invalid_intervals.append((invalid_after, int(stamp)))
            pending_invalid = False
        voltage = _number(getattr(row, "Volt", None))
        current = _number(getattr(row, "Curr", None))
        rows.append(
            (
                int(stamp),
                voltage if voltage and voltage > 0 else None,
                current if current is not None and current >= 0 else None,
            )
        )
    if pending_invalid:
        invalid_intervals.append((invalid_after, None))
    return rows, invalid_intervals


def _invalid_near(intervals, start_us, end_us):
    """Use source-order neighbors to scope an untimeable record conservatively."""
    return any(
        (before is None or before <= end_us) and (after is None or after >= start_us)
        for before, after in intervals
    )


def _smoothed(rows):
    values = []
    for stamp, _, _ in rows:
        trailing = [
            current
            for time, _, current in rows
            if stamp - SMOOTH_US <= time <= stamp and current is not None
        ]
        values.append(float(median(trailing)) if len(trailing) >= 3 else None)
    return values


def detect_load_onset(
    bat: pd.DataFrame, instance: int, trigger_us: int, anchor_us: int
) -> int | None:
    """Find a confirmed current ramp inside an independently established context.

    A stable low-current baseline and sustained ramp samples within 0.5 s are
    required. The onset threshold uses baseline current, never eventual peak.
    """
    rows, invalid_intervals = _samples(bat, instance)
    rows = [
        row for row in rows if trigger_us - 3_000_000 <= row[0] <= anchor_us + SMOOTH_US
    ]
    if (
        _invalid_near(invalid_intervals, trigger_us - 3_000_000, anchor_us + SMOOTH_US)
        or len(rows) < 6
        or any(b[0] <= a[0] or b[0] - a[0] > GAP_US for a, b in zip(rows, rows[1:]))
        or any(row[1] is None or row[2] is None for row in rows)
    ):
        return None
    candidates = []
    for index, row in enumerate(rows):
        if row[0] < trigger_us:
            continue
        if row[0] > anchor_us:
            break
        prior = [
            item[2] for item in rows[:index] if row[0] - 3_000_000 <= item[0] < row[0]
        ]
        if len(prior) < 10 or row[0] - rows[0][0] < 1_000_000:
            continue
        baseline = median(prior)
        spread = median(abs(value - baseline) for value in prior)
        if (
            baseline <= 0
            or baseline > 5
            or spread > max(0.1, 0.1 * baseline)
            or row[2] < baseline + max(0.25, 0.25 * baseline)
            or rows[index - 1][2] >= baseline + max(0.25, 0.25 * baseline)
        ):
            continue
        later = [item for item in rows[index:] if item[0] <= row[0] + SMOOTH_US]
        if (
            len(later) >= 5
            and later[-1][0] - row[0] >= 300_000
            and later[1][2] >= later[0][2] * 0.85
            and later[2][2] >= later[1][2] * 0.85
            and later[2][2] >= baseline + max(2.0, 2 * baseline)
            and sum(item[2] >= baseline + max(2.0, 2 * baseline) for item in later) >= 3
        ):
            if any(
                item[2] < baseline + max(0.25, 0.25 * baseline)
                for item in rows[index + 1 :]
                if item[0] <= anchor_us
            ):
                return None  # transient/repeated pre-boundary bursts are ambiguous
            candidates.append(row[0])
    return candidates[0] if len(candidates) == 1 else None


def detect_auto_load_onset(
    bat: pd.DataFrame, instance: int, trigger_us: int, anchor_us: int
) -> int | None:
    """Keep the Slice 1 AUTO onset contract and algorithm unchanged."""
    return detect_load_onset(bat, instance, trigger_us, anchor_us)


def _baseline(rows, invalid_intervals, t0_us, reference):
    """Qualify a recent, contiguous, stable low-current BAT run before T0."""
    if _invalid_near(invalid_intervals, t0_us - 3_000_000, t0_us):
        return None, None
    prior = [row for row in rows if t0_us - 3_000_000 <= row[0] < t0_us]
    if not prior or t0_us - prior[-1][0] > GAP_US:
        return None, None
    run = []
    previous = t0_us
    for row in reversed(prior):
        if (
            previous - row[0] > GAP_US
            or row[1] is None
            or row[2] is None
            or row[2] > 0.3 * reference
        ):
            break
        run.append(row)
        previous = row[0]
    # Search only suffixes ending nearest T0. An earlier transient may be
    # excluded, but a late transition cannot be bypassed. Ten nominal 10 Hz
    # samples span 0.9 s. Full ranges catch step changes hidden by MAD.
    for count in range(len(run), 9, -1):
        candidate = run[:count]
        if candidate[0][0] - candidate[-1][0] < 900_000:
            continue
        current = float(median(row[2] for row in candidate))
        voltage = float(median(row[1] for row in candidate))
        # Allow ordinary BAT noise, but reject a load step or material sag.
        if (
            max(row[2] for row in candidate) - min(row[2] for row in candidate)
            <= max(0.5, 0.2 * current)
            and max(row[1] for row in candidate) - min(row[1] for row in candidate)
            <= max(0.1, 0.01 * voltage)
        ):
            return voltage, current
    return None, None


def evaluate_load_response(
    bat: pd.DataFrame, instance: int, t0_us: int | None, end_us: int
) -> BatteryLoadResponse:
    """Measure one independently established load onset, without persistence."""

    def unavailable(reason):
        return BatteryLoadResponse(
            t0_us,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            reason,
        )

    if t0_us is None:
        return unavailable("Load onset unavailable; no reliable pre-load transition.")
    rows, invalid_intervals = _samples(bat, instance)
    rows = [row for row in rows if row[0] <= end_us]
    window = [row for row in rows if t0_us <= row[0] <= t0_us + HORIZON_US]
    if not window or _invalid_near(
        invalid_intervals, t0_us - 3_000_000, t0_us + HORIZON_US
    ):
        return unavailable("BAT samples or timestamps incomplete.")
    gaps = any(b[0] <= a[0] or b[0] - a[0] > GAP_US for a, b in zip(window, window[1:]))
    missing_values = any(row[1] is None or row[2] is None for row in window)
    reference_rows = [row for row in window if row[0] <= t0_us + 6_000_000]
    reference_incomplete = (
        end_us < t0_us + 6_000_000
        or not reference_rows
        or reference_rows[0][0] - t0_us > GAP_US
        or reference_rows[-1][0] < t0_us + 6_000_000 - GAP_US
        or any(row[2] is None for row in reference_rows)
        or any(
            b[0] <= a[0] or b[0] - a[0] > GAP_US
            for a, b in zip(reference_rows, reference_rows[1:])
        )
    )
    if reference_incomplete:
        measured = [row for row in window if row[0] <= min(t0_us + HORIZON_US, end_us)]
        voltage_rows = [row for row in measured if row[1] is not None]
        minimum = min(voltage_rows, key=lambda row: row[1]) if voltage_rows else None
        currents = [row[2] for row in measured if row[2] is not None]
        return BatteryLoadResponse(
            t0_us,
            None,
            None,
            None,
            max(currents) if currents else None,
            None,
            None,
            minimum[1] if minimum else None,
            minimum[2] if minimum else None,
            None,
            None,
            None,
            None,
            min(t0_us + HORIZON_US, end_us),
            "Current reference unavailable: incomplete BAT evidence in first 6 s; "
            "T1 qualification unavailable.",
            True,
        )
    smooth = _smoothed(reference_rows)
    valid_smooth = [value for value in smooth if value is not None]
    if len(valid_smooth) < 3:
        return unavailable("Smoothed high-load current unavailable.")
    reference = float(pd.Series(valid_smooth).quantile(0.9))
    if reference <= 0:
        return unavailable("High-load reference current unavailable.")
    threshold = 0.8 * reference
    baseline_v, baseline_i = _baseline(rows, invalid_intervals, t0_us, reference)
    peak_index = max(range(len(smooth)), key=lambda i: smooth[i] or -1)
    all_smooth = _smoothed(window)
    t1 = None
    for index in range(peak_index + 1, len(window)):
        stamp = window[index][0]
        if all_smooth[index] is None or all_smooth[index] >= threshold:
            continue
        confirmation_end = next(
            (
                j
                for j in range(index, len(window))
                if window[j][0] >= stamp + CONFIRM_US
            ),
            None,
        )
        if confirmation_end is None:
            continue
        confirmation = range(index, confirmation_end + 1)
        if all(
            window[j][2] is not None
            and all_smooth[j] is not None
            and all_smooth[j] < threshold
            for j in confirmation
        ) and all(
            0 < window[j + 1][0] - window[j][0] <= GAP_US for j in confirmation[:-1]
        ):
            t1 = stamp
            break
    observation_end = t1 if t1 is not None else min(t0_us + HORIZON_US, end_us)
    measured = [row for row in window if row[0] <= observation_end]
    voltage_rows = [row for row in measured if row[1] is not None]
    minimum = min(voltage_rows, key=lambda row: row[1]) if voltage_rows else None
    currents = [row[2] for row in measured if row[2] is not None]
    follow_target = observation_end + 5_000_000
    follow = next(
        (
            row
            for row in rows
            if follow_target <= row[0] <= follow_target + GAP_US
            and row[1] is not None
            and row[2] is not None
        ),
        None,
    )
    truncated = t1 is None and (
        end_us < t0_us + HORIZON_US or window[-1][0] < t0_us + HORIZON_US - GAP_US
    )
    status = (
        "Confirmed 80% current reduction."
        if t1 is not None
        else "High-load end not established; observation truncated."
        if truncated
        else "High-load end not established; 20-second observation window."
    )
    if gaps:
        status += " BAT continuity incomplete."
    if missing_values:
        status += " BAT voltage/current samples incomplete."
    if baseline_v is None:
        status += " Low-current voltage/current baseline unavailable."
    if follow is None:
        status += " Five-second follow-up unavailable within 0.4 s of target."
    reaccelerated = t1 is not None and any(
        value is not None and value >= threshold
        for row, value in zip(window, all_smooth)
        if row[0] > t1 + CONFIRM_US
    )
    if reaccelerated:
        status += " Later re-acceleration observed; T1 is not final load end."
    return BatteryLoadResponse(
        t0_us,
        t1,
        reference,
        threshold,
        max(currents) if currents else None,
        baseline_v,
        baseline_i,
        minimum[1] if minimum else None,
        minimum[2] if minimum else None,
        baseline_v - minimum[1] if baseline_v is not None and minimum else None,
        follow[0] if follow else None,
        follow[1] if follow else None,
        follow[2] if follow else None,
        observation_end,
        status,
        gaps,
        reaccelerated,
    )
