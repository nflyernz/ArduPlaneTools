"""Event-based battery voltage failsafe evidence for Battery Analysis.

The replay uses recorded BAT samples and effective embedded PARM values. It is
not a prediction of the trajectory that would follow a different failsafe.
"""

import math
import re
from bisect import bisect_right
from dataclasses import dataclass, replace

from .flight_data import FlightLog
from .flight_window import FlightWindow

MAX_SAMPLE_GAP_US = 400_000
# Any effective change, including a value changed and restored between BAT
# records, interrupts the evidence for a continuously qualified excursion.
REPLAY_PARAM_SUFFIXES = (
    "LOW_VOLT", "CRT_VOLT", "LOW_TIMER", "FS_VOLTSRC",
    "FS_LOW_ACT", "FS_CRT_ACT", "LOW_MAH", "CRT_MAH",
)
BATTERY_MESSAGE = re.compile(r"battery\s+(\d+)\s+is\s+(low|critical)", re.IGNORECASE)


@dataclass(frozen=True)
class FailsafeConfiguration:
    """Parameters effective at a BAT sample, for one monitor."""

    low_v: float | None
    critical_v: float | None
    timer_s: float | None
    source: int | None
    low_action: int | None
    critical_action: int | None
    low_mah: float | None
    critical_mah: float | None


@dataclass(frozen=True)
class VoltageExcursion:
    """One contiguous run under the same configuration and armed session."""

    instance: int
    source: str
    stage: str
    start_us: int
    end_us: int
    first_qualification_us: int | None
    minimum_v: float
    maximum_current_a: float | None
    consumed_mah_at_end: float | None
    configuration: FailsafeConfiguration
    armed_session: int | None
    gap_after: bool
    qualification_outside_window: str | None = None

    @property
    def duration_s(self) -> float:
        return (self.end_us - self.start_us) / 1_000_000

    @property
    def selected_source(self) -> bool:
        return (self.configuration.source == 0 and self.source == "raw") or (
            self.configuration.source == 1 and self.source == "compensated"
        )


@dataclass(frozen=True)
class ObservedBatteryFailsafe:
    """Battery status text with a nearby logged mode transition, if present."""

    time_us: int
    stage: str
    message: str
    mode_time_us: int | None
    mode_number: int | None
    mode_reason: int | None


@dataclass(frozen=True)
class VoltageFailsafeAssessment:
    """Read-only evidence for a BAT instance and optional flight window."""

    instance: int
    excursions: tuple[VoltageExcursion, ...]
    observed: tuple[ObservedBatteryFailsafe, ...]
    compensation_unavailable: bool
    compensation_reason: str | None
    sample_count: int
    starting_configuration: FailsafeConfiguration | None = None
    raw_unavailable: bool = False
    sampling_gaps: bool = False


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _time(value) -> int | None:
    number = _finite(value)
    return (
        int(number)
        if number is not None and number >= 0 and number.is_integer()
        else None
    )


def _parameter(flight_log: FlightLog, name: str, time_us: int) -> float | None:
    return _finite(flight_log.parameter_history.value_at(name, time_us))


def _configuration(
    flight_log: FlightLog, instance: int, time_us: int
) -> FailsafeConfiguration:
    prefix = "BATT" if instance == 0 else f"BATT{instance + 1}"
    def value(suffix):
        return _parameter(flight_log, f"{prefix}_{suffix}", time_us)
    source = value("FS_VOLTSRC")
    low_action = value("FS_LOW_ACT")
    critical_action = value("FS_CRT_ACT")
    return FailsafeConfiguration(
        low_v=value("LOW_VOLT"),
        critical_v=value("CRT_VOLT"),
        timer_s=value("LOW_TIMER"),
        source=int(source) if source in (0, 1) else None,
        low_action=int(low_action) if low_action is not None else None,
        critical_action=int(critical_action) if critical_action is not None else None,
        low_mah=value("LOW_MAH"),
        critical_mah=value("CRT_MAH"),
    )


def _configuration_change_times(flight_log: FlightLog, instance: int) -> list[int]:
    """Return all relevant PARM timestamps, including intermediate reversals.

    Looking up the configuration only when BAT records arrive loses a parameter
    change that is reversed before the next sample. A timer must not bridge it.
    """
    prefix = "BATT" if instance == 0 else f"BATT{instance + 1}"
    history = flight_log.parameter_history.changes
    times = {
        time_us
        for suffix in REPLAY_PARAM_SUFFIXES
        for change in history.get(f"{prefix}_{suffix}", ())
        if (time_us := _time(change.time_us)) is not None
    }
    return sorted(times)


def _armed_windows(flight_log: FlightLog) -> list[tuple[int, int]]:
    arm = flight_log.get("ARM")
    if arm.empty or not {"TimeUS", "ArmState"}.issubset(arm.columns):
        return []
    windows: list[tuple[int, int]] = []
    start = None
    for row in arm.itertuples(index=False):
        time_us = _time(row.TimeUS)
        state = _finite(row.ArmState)
        if time_us is None or state is None:
            continue
        if state and start is None:
            start = time_us
        elif not state and start is not None:
            windows.append((start, time_us))
            start = None
    if start is not None:
        windows.append((start, math.inf))
    return windows


def _session(time_us: int, windows: list[tuple[int, int]]) -> int | None:
    return next(
        (
            index + 1
            for index, (start, end) in enumerate(windows)
            if start <= time_us <= end
        ),
        None,
    )


def _observed(
    flight_log: FlightLog, instance: int, window: FlightWindow | None
) -> tuple[ObservedBatteryFailsafe, ...]:
    messages = flight_log.get("MSG")
    modes = flight_log.get("MODE")
    if messages.empty or not {"TimeUS", "Message"}.issubset(messages.columns):
        return ()
    mode_rows = []
    if not modes.empty and {"TimeUS", "ModeNum"}.issubset(modes.columns):
        for row in modes.itertuples(index=False):
            time_us = _time(row.TimeUS)
            mode = _finite(row.ModeNum)
            reason = _finite(getattr(row, "Rsn", None))
            if time_us is not None and mode is not None:
                mode_rows.append(
                    (time_us, int(mode), int(reason) if reason is not None else None)
                )
    found = []
    for row in messages.itertuples(index=False):
        time_us = _time(row.TimeUS)
        message = str(row.Message)
        match = BATTERY_MESSAGE.search(message)
        if (
            time_us is None
            or match is None
            or int(match.group(1)) != instance + 1
            or window is not None
            and not window.start_us <= time_us <= window.end_us
        ):
            continue
        near = [mode for mode in mode_rows if abs(mode[0] - time_us) <= 2_000_000]
        matching = [mode for mode in near if mode[1] == 11 and mode[2] == 4]
        closest = (
            min(matching or near, key=lambda mode: abs(mode[0] - time_us))
            if near
            else (None, None, None)
        )
        found.append(
            ObservedBatteryFailsafe(time_us, match.group(2).lower(), message, *closest)
        )
    return tuple(found)


def assess_voltage_failsafe(
    flight_log: FlightLog, instance: int, window: FlightWindow | None = None
) -> VoltageFailsafeAssessment:
    """Scan BAT in logged order; split at gaps, reboots, configuration and arm changes."""
    bat = flight_log.get("BAT")
    if bat.empty or not {"TimeUS", "Inst", "Volt"}.issubset(bat.columns):
        return VoltageFailsafeAssessment(
            instance,
            (),
            _observed(flight_log, instance, window),
            True,
            "BAT voltage samples unavailable",
            0,
        )
    parameter_changes = _configuration_change_times(flight_log, instance)
    windows = _armed_windows(flight_log)
    # Flight windows also prevent a run from joining separate flights when ARM
    # telemetry is absent. ARM windows take precedence where available.
    if not windows:
        windows = [(flight.start_us, flight.end_us) for flight in flight_log.flights]
    active = {}
    events = []
    previous_us = None
    unavailable = False
    raw_unavailable = False
    sampling_gaps = False
    sample_count = 0
    starting_configuration = None

    def finish(key, gap=False):
        run = active.pop(key, None)
        if run is not None:
            events.append(
                VoltageExcursion(
                    instance,
                    key[0],
                    key[1],
                    run["start_us"],
                    run["end_us"],
                    run["qualified_us"],
                    run["minimum_v"],
                    run["maximum_current_a"],
                    run["consumed_mah"],
                    run["configuration"],
                    run["session"],
                    gap,
                )
            )

    for row in bat.itertuples(index=False):
        if _finite(row.Inst) != instance:
            continue
        time_us = _time(row.TimeUS)
        if time_us is None:
            sampling_gaps = True
            for key in list(active):
                finish(key, gap=True)
            continue
        in_window = window is None or window.start_us <= time_us <= window.end_us
        if in_window:
            sample_count += 1
        gap = previous_us is not None and (
            time_us <= previous_us or time_us - previous_us > MAX_SAMPLE_GAP_US
        )
        if gap:
            if window is None or (
                previous_us <= window.end_us and time_us >= window.start_us
            ):
                sampling_gaps = True
            for key in list(active):
                finish(key, gap=True)
        elif previous_us is not None and (
            bisect_right(parameter_changes, previous_us)
            < bisect_right(parameter_changes, time_us)
        ):
            # A relevant PARM change interrupts continuous qualification,
            # even if it was undone before this BAT sample.
            for key in list(active):
                finish(key)
        previous_us = time_us
        raw = _finite(row.Volt)
        if in_window and (raw is None or raw <= 0):
            raw_unavailable = True
        current = _finite(getattr(row, "Curr", None))
        consumed = _finite(getattr(row, "CurrTot", None))
        resting = _finite(getattr(row, "VoltR", None))
        resistance = _finite(getattr(row, "Res", None))
        healthy = _finite(getattr(row, "H", None))
        valid_compensation = (
            raw is not None
            and raw > 0
            and resting is not None
            and resting > 0
            and current is not None
            and 0 <= current <= 1000
            and resistance is not None
            and 0 <= resistance <= 2
            and healthy is not None
            and healthy > 0
            and resting <= raw * 2
        )
        if not valid_compensation and in_window:
            unavailable = True
        source_values = {
            "raw": raw,
            "compensated": max(raw, resting) if valid_compensation else None,
        }
        configuration = _configuration(flight_log, instance, time_us)
        if in_window and starting_configuration is None:
            starting_configuration = configuration
        session = _session(time_us, windows)
        for source, voltage in source_values.items():
            for stage, threshold in (
                ("low", configuration.low_v),
                ("critical", configuration.critical_v),
            ):
                key = (source, stage)
                run = active.get(key)
                signature = (configuration, session)
                if run is not None and run["signature"] != signature:
                    finish(key)
                    run = None
                below = (
                    voltage is not None
                    and voltage > 0
                    and threshold is not None
                    and threshold > 0
                    and configuration.timer_s is not None
                    and configuration.timer_s > 0
                    and voltage < threshold
                )
                if not below:
                    finish(key)
                    continue
                if run is None:
                    active[key] = {
                        "start_us": time_us,
                        "end_us": time_us,
                        "qualified_us": None,
                        "minimum_v": voltage,
                        "maximum_current_a": current,
                        "consumed_mah": consumed,
                        "configuration": configuration,
                        "session": session,
                        "signature": signature,
                    }
                else:
                    run["end_us"] = time_us
                    run["minimum_v"] = min(run["minimum_v"], voltage)
                    if current is not None:
                        run["maximum_current_a"] = max(
                            run["maximum_current_a"] or current, current
                        )
                    if consumed is not None:
                        run["consumed_mah"] = consumed
                    if (
                        run["qualified_us"] is None
                        and time_us - run["start_us"]
                        >= configuration.timer_s * 1_000_000
                    ):
                        run["qualified_us"] = time_us
    for key in list(active):
        finish(key)
    if window is not None:
        selected = []
        for event in events:
            if event.start_us > window.end_us or event.end_us < window.start_us:
                continue
            qualification = event.first_qualification_us
            if qualification is not None and not (
                window.start_us <= qualification <= window.end_us
            ):
                # Preserve evidence that a run overlaps the flight, but do
                # not count a qualification outside the selected flight.
                side = "before" if qualification < window.start_us else "after"
                event = replace(
                    event,
                    first_qualification_us=None,
                    qualification_outside_window=side,
                )
            selected.append(event)
        events = selected
    return VoltageFailsafeAssessment(
        instance,
        tuple(events),
        _observed(flight_log, instance, window),
        unavailable,
        "missing or invalid VoltR/current/resistance/BAT.H" if unavailable else None,
        sample_count,
        starting_configuration,
        raw_unavailable,
        sampling_gaps,
    )
