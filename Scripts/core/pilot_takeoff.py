"""Read-only, conservative ground-to-flight evidence for pilot-controlled launches.

Candidate boundaries come from GPS speed transitions. POS climb, a prior ground
state, propulsion demand and flight mode must independently agree. STAT is not
used as a decisive ground/air signal because it can be true during taxi.
"""

import math
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

import pandas as pd

GPS_GAP_US = 600_000
GROUND_SPEED_M_S = 2.5
FLIGHT_SPEED_M_S = 5.0
GROUND_CONFIRM_US = 1_000_000
FLIGHT_CONFIRM_US = 2_000_000
CLIMB_CONFIRM_M = 10.0
CLIMB_FOLLOW_THROUGH_US = 2_000_000
LAUNCH_POWER_END_US = 1_000_000


@dataclass(frozen=True)
class PilotTakeoffEvent:
    time_us: int
    flight_start_us: int
    mode_number: int
    mode_name: str
    ground_time_us: int
    climb_time_us: int
    ground_altitude_m: float
    climb_m: float
    ground_speed_m_s: float
    throttle_pct: float
    stat_flying_before: bool | None


@dataclass(frozen=True)
class TakeoffCandidate:
    time_us: int
    reason: str


@dataclass(frozen=True)
class PilotTakeoffScan:
    events: tuple[PilotTakeoffEvent, ...]
    rejected: tuple[TakeoffCandidate, ...]


def _rows(frame, columns):
    if frame is None or frame.empty or not {"TimeUS", *columns}.issubset(frame.columns):
        return []
    data = frame[["TimeUS", *columns]].apply(pd.to_numeric, errors="coerce")
    data = data.replace([float("inf"), float("-inf")], float("nan"))
    data = data.dropna().sort_values("TimeUS", kind="stable")
    return [tuple(row) for row in data.itertuples(index=False, name=None)]


def _invalid_intervals(frame, columns):
    """Locate unusable records by their source-order neighbors."""
    if frame is None or frame.empty or not {"TimeUS", *columns}.issubset(frame.columns):
        return []
    data = frame[["TimeUS", *columns]].apply(pd.to_numeric, errors="coerce")
    intervals = []
    last = None
    pending = False
    for row in data.itertuples(index=False, name=None):
        stamp = row[0]
        if (not math.isfinite(stamp) or stamp < 0 or stamp != int(stamp)
                or any(not math.isfinite(value) for value in row[1:])):
            pending = True
            continue
        if pending or last is not None and stamp <= last:
            intervals.append((last, stamp))
        pending = False
        last = stamp
    if pending:
        intervals.append((last, None))
    return intervals


def _corrupt_near(intervals, start, end):
    return any((before is None or before <= end)
               and (after is None or after >= start)
               for before, after in intervals)


def _near(rows, start, end):
    return [row for row in rows if start <= row[0] <= end]


def _continuous(rows, maximum_gap=GPS_GAP_US):
    return bool(rows) and all(
        0 < later[0] - earlier[0] <= maximum_gap
        for earlier, later in pairwise(rows)
    )


def _mode_at(modes, stamp):
    prior = [row for row in modes if row[0] <= stamp]
    return int(prior[-1][1]) if prior else None


def detect_pilot_takeoffs(flight_log) -> PilotTakeoffScan:
    """Return confirmed events and explicit rejected GPS transition candidates."""
    gps = _rows(flight_log.get("GPS"), ("Spd",))
    pos = _rows(flight_log.get("POS"), ("RelHomeAlt",))
    ctun = _rows(flight_log.get("CTUN"), ("ThO",))
    modes = _rows(flight_log.get("MODE"), ("ModeNum",))
    stat = _rows(flight_log.get("STAT"), ("isFlying",))
    gps_invalid = _invalid_intervals(flight_log.get("GPS"), ("Spd",))
    pos_invalid = _invalid_intervals(flight_log.get("POS"), ("RelHomeAlt",))
    ctun_invalid = _invalid_intervals(flight_log.get("CTUN"), ("ThO",))
    if not gps or not pos or not ctun or not modes:
        return PilotTakeoffScan((), (TakeoffCandidate(0, "Essential GPS/POS/CTUN/MODE telemetry unavailable."),))
    events = []
    rejected = []
    for index, (time_us, speed) in enumerate(gps):
        if speed <= FLIGHT_SPEED_M_S or index and gps[index - 1][1] > FLIGHT_SPEED_M_S:
            continue
        stamp = int(time_us)
        mode = _mode_at(modes, stamp)
        if mode == 13:
            rejected.append(TakeoffCandidate(stamp, "AUTO mode; handled by existing detector."))
            continue
        if mode not in (0, 5):
            rejected.append(TakeoffCandidate(stamp, "Mode is neither MANUAL nor FBWA."))
            continue
        flight = next((window for window in flight_log.flights
                       if window.start_us - FLIGHT_CONFIRM_US <= stamp <= window.end_us), None)
        if flight is None:
            rejected.append(TakeoffCandidate(stamp, "No supporting FlightWindow."))
            continue
        if _corrupt_near(gps_invalid, stamp - 10_000_000, stamp + 3_000_000):
            rejected.append(TakeoffCandidate(stamp, "Essential telemetry contains invalid or reversed records."))
            continue
        high = _near(gps, stamp, stamp + FLIGHT_CONFIRM_US + GPS_GAP_US)
        confirmation_end = next((j for j, row in enumerate(high)
                                 if row[0] >= stamp + FLIGHT_CONFIRM_US), None)
        high = high[:confirmation_end + 1] if confirmation_end is not None else []
        if (len(high) < 5
                or not _continuous(high) or any(row[1] <= FLIGHT_SPEED_M_S for row in high)):
            rejected.append(TakeoffCandidate(stamp, "Groundspeed did not persist."))
            continue
        low = _near(gps, stamp - 10_000_000, stamp)
        low_runs = []
        run = []
        for row in low:
            if row[1] <= GROUND_SPEED_M_S and (not run or row[0] - run[-1][0] <= GPS_GAP_US):
                run.append(row)
            else:
                if run:
                    low_runs.append(run)
                run = [row] if row[1] <= GROUND_SPEED_M_S else []
        if run:
            low_runs.append(run)
        ground = next((run for run in reversed(low_runs)
                       if run[-1][0] >= stamp - 4_000_000
                       and run[-1][0] - run[0][0] >= GROUND_CONFIRM_US), None)
        if ground is None:
            rejected.append(TakeoffCandidate(stamp, "No recent persistent low-speed ground state."))
            continue
        # A speed dip while power remains on can occur in flight. Once
        # high-speed flight has preceded this low-speed run, require a
        # sustained reduced-power phase before treating it as a landing.
        previously_fast = any(
            row[1] > FLIGHT_SPEED_M_S
            for row in gps if flight.start_us <= row[0] < ground[0][0]
        )
        ground_power = _near(ctun, ground[0][0], ground[-1][0])
        power_confirmed = False
        power_run = []
        for row in ground_power:
            if row[1] <= 20 and (not power_run or row[0] - power_run[-1][0] <= GPS_GAP_US):
                power_run.append(row)
                if row[0] - power_run[0][0] >= 400_000:
                    power_confirmed = True
                    break
            else:
                power_run = [row] if row[1] <= 20 else []
        if previously_fast and not power_confirmed:
            rejected.append(TakeoffCandidate(stamp, "No established landing before renewed acceleration."))
            continue
        # Use a stable ground segment before acceleration. A pressure-derived
        # POS dip during the ground roll must not erase earlier ground proof.
        pre_pos = _near(pos, stamp - 8_000_000, stamp - 500_000)
        ground_alt = None
        for endpoint in reversed(pre_pos):
            segment = _near(pre_pos, endpoint[0] - 1_000_000, endpoint[0])
            if (len(segment) < 5 or segment[-1][0] - segment[0][0] < 900_000
                    or not _continuous(segment)):
                continue
            altitude = float(median(row[1] for row in segment))
            if max(row[1] for row in segment) - min(row[1] for row in segment) <= 1.5:
                ground_alt = altitude
                break
        if ground_alt is None:
            rejected.append(TakeoffCandidate(stamp, "No stable near-ground altitude before acceleration."))
            continue
        future_pos = _near(pos, stamp, stamp + 20_000_000 + CLIMB_FOLLOW_THROUGH_US)
        climb = None
        for row in future_pos:
            if row[0] < stamp + 2_000_000 or row[0] > stamp + 20_000_000:
                continue
            if row[1] < ground_alt + CLIMB_CONFIRM_M:
                continue
            proof_end = row[0] + CLIMB_FOLLOW_THROUGH_US
            proof = _near(future_pos, stamp, proof_end)
            follow_through = _near(future_pos, row[0], proof_end)
            if (proof and proof[0][0] - stamp <= GPS_GAP_US
                    and follow_through[-1][0] >= proof_end - GPS_GAP_US
                    and len(follow_through) >= 5
                    and _continuous(proof)
                    and not _corrupt_near(pos_invalid, stamp - 8_000_000, proof_end)
                    and median(item[1] for item in follow_through) >= ground_alt + CLIMB_CONFIRM_M):
                climb = row
                break
        if climb is None:
            rejected.append(TakeoffCandidate(stamp, "No continuous sustained climb of 10 m within 20 s."))
            continue
        demand = _near(ctun, stamp - 4_000_000, stamp + LAUNCH_POWER_END_US)
        high_throttle = [row[1] for row in demand if row[1] >= 20]
        launch_power = [row for row in demand
                        if stamp - 500_000 <= row[0] <= stamp + LAUNCH_POWER_END_US
                        and row[1] >= 20]
        if (len(high_throttle) < 3 or not launch_power or not _continuous(demand)
                or _corrupt_near(ctun_invalid, stamp - 4_000_000,
                                 stamp + LAUNCH_POWER_END_US)):
            rejected.append(TakeoffCandidate(stamp, "Propulsion demand unavailable or insufficient."))
            continue
        earlier_stat = [row for row in stat if row[0] <= stamp]
        stat_flying = bool(earlier_stat[-1][1]) if earlier_stat else None
        events.append(PilotTakeoffEvent(
            stamp, flight.start_us, mode, "MANUAL" if mode == 0 else "FBWA",
            int(ground[-1][0]), int(climb[0]), ground_alt,
            float(climb[1] - ground_alt), float(speed), float(max(high_throttle)),
            stat_flying,
        ))
    return PilotTakeoffScan(tuple(events), tuple(rejected))
