"""
Flight-scoped battery telemetry processing.

BAT counters are cumulative across a log, so consumption values are
calculated as deltas from the selected FlightWindow baseline.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd

from .battery_failsafe import VoltageFailsafeAssessment, assess_voltage_failsafe
from .battery_load_response import (
    BatteryLoadResponse,
    detect_auto_load_onset,
    evaluate_load_response,
)
from .config import Config
from .flight_data import FlightLog
from .flight_window import FlightWindow
from .pilot_battery_onset import (
    GpsAnchoredBatteryObservation,
    PilotLoadOnset,
    detect_pilot_load_onset,
    observe_gps_anchored_bat,
)
from .pilot_plateau_voltage import (
    ObservedPlateauVoltageComparison,
    evaluate_observed_plateau_voltage,
)
from .pilot_takeoff import PilotTakeoffEvent, detect_pilot_takeoffs
from .scope import filter_telemetry, validate_flight_window


@dataclass
class BatteryLoadEvent:
    """Measurements associated with the highest-current BAT sample."""

    time_us: int
    current: float
    voltage_before: Optional[float]
    minimum_voltage: Optional[float]
    voltage_sag: Optional[float]
    sag_per_ampere: Optional[float]
    voltage_after_recovery: Optional[float]
    voltage_recovery: Optional[float]


class BatteryLoadEventType(Enum):
    """Supported bounded battery load-event families."""

    TAKEOFF = "TAKEOFF"
    SUSTAINED_HIGH_THROTTLE = "SUSTAINED_HIGH_THROTTLE"


class TakeoffType(Enum):
    """Takeoff classifications supported by validated evidence."""

    AUTO = "AUTO"
    PILOT_CONTROLLED = "PILOT_CONTROLLED"


@dataclass(frozen=True)
class PilotTakeoffMeasurement:
    """Read-only event proof and BAT response; never a history observation."""

    event: PilotTakeoffEvent
    response: BatteryLoadResponse
    takeoff_type: TakeoffType = TakeoffType.PILOT_CONTROLLED
    onset: PilotLoadOnset | None = None
    gps_observation: GpsAnchoredBatteryObservation | None = None
    plateau_comparison: ObservedPlateauVoltageComparison | None = None


@dataclass(frozen=True)
class BatterySessionConfiguration:
    """Stable embedded battery configuration for one analysed session."""

    lookup_time_us: int
    capacity_mah: Optional[float]
    low_voltage: Optional[float]
    critical_voltage: Optional[float]
    failsafe_voltage_source: Optional[float]
    warnings: tuple[str, ...] = ()

    @property
    def raw_voltage_margins_supported(self) -> bool:
        """Return whether configured thresholds apply to raw BAT.Volt."""
        return self.failsafe_voltage_source == 0.0


@dataclass(frozen=True)
class BatteryLoadInterval:
    """Battery evidence measured over one bounded load interval."""

    event_type: BatteryLoadEventType
    takeoff_type: Optional[TakeoffType]
    flight_number: int
    instance: int
    start_us: int
    end_us: int
    duration_s: float
    consumed_mah_at_start: Optional[float]
    pre_load_voltage: Optional[float]
    minimum_voltage: Optional[float]
    current_at_minimum_voltage: Optional[float]
    peak_current: Optional[float]
    average_current: Optional[float]
    maximum_throttle: Optional[float]
    average_throttle: Optional[float]
    voltage_sag: Optional[float]
    recovery_time_us: Optional[int]
    voltage_after_recovery: Optional[float]
    voltage_recovery: Optional[float]
    low_voltage_margin: Optional[float]
    critical_voltage_margin: Optional[float]


@dataclass(frozen=True)
class _BatteryLoadBounds:
    """Internal event bounds produced before telemetry evaluation."""

    event_type: BatteryLoadEventType
    takeoff_type: Optional[TakeoffType]
    start_us: int
    end_us: int


@dataclass
class BatteryAnalysis:
    """Battery measurements for one BAT instance and FlightWindow."""

    instance: int
    start_us: int
    end_us: int
    duration_s: Optional[float]
    start_voltage: Optional[float]
    final_voltage: Optional[float]
    minimum_voltage: Optional[float]
    maximum_current: Optional[float]
    average_current: Optional[float]
    maximum_power: Optional[float]
    consumed_mah: Optional[float]
    consumed_wh: Optional[float]
    mah_per_minute: Optional[float]
    load_event: Optional[BatteryLoadEvent]
    counter_warnings: list[str] = field(default_factory=list)
    session_configuration: Optional[BatterySessionConfiguration] = None
    bounded_load_events: list[BatteryLoadInterval] = field(
        default_factory=list
    )
    voltage_failsafe: VoltageFailsafeAssessment | None = None
    battery_load_response: BatteryLoadResponse | None = None
    pilot_controlled_takeoffs: list[PilotTakeoffMeasurement] = field(default_factory=list)


class BatteryProcessor:
    """
    Analyse one explicit ArduPilot BAT instance within one FlightWindow.

    The initial load-event definition is deliberately simple: the event is
    the single in-window BAT sample with the highest valid current. Its
    minimum voltage is therefore that sample's voltage.
    """

    RECOVERY_US = 5_000_000

    def __init__(
        self,
        flight_log: FlightLog,
        flight_window: FlightWindow,
        instance: int,
        config=None,
    ):
        validate_flight_window(flight_log, flight_window)

        self.flight_log = flight_log
        self.flight_window = flight_window
        self.instance = int(instance)
        self.config = config or Config("Config/battery.yaml")

    def available_instances(self) -> list[int]:
        """Return BAT instances with valid instance identifiers."""
        bat = self.flight_log.get("BAT")

        if bat is None or bat.empty or "Inst" not in bat.columns:
            return []

        instances = pd.to_numeric(bat["Inst"], errors="coerce").dropna()
        return sorted({int(value) for value in instances})

    def analyse(self) -> Optional[BatteryAnalysis]:
        """Return measurements for the selected instance, or None if absent."""
        bat = self.flight_log.get("BAT")

        if (
            bat is None
            or bat.empty
            or not {"TimeUS", "Inst"}.issubset(bat.columns)
        ):
            return None

        all_instance = self._instance_rows(bat)

        if all_instance.empty:
            return None

        scoped = filter_telemetry(
            all_instance,
            self.flight_window,
        ).copy()

        if scoped.empty:
            return None

        scoped = scoped.sort_values("TimeUS")
        duration_s = self._duration_s()
        warnings: list[str] = []

        start_voltage = self._first_value(scoped, "Volt")
        final_voltage = self._last_value(scoped, "Volt")
        minimum_voltage = self._minimum_value(scoped, "Volt")
        maximum_current = self._maximum_value(scoped, "Curr")
        average_current = self._mean_value(scoped, "Curr")
        maximum_power = self._maximum_power(scoped)

        consumed_mah = self._counter_delta(
            all_instance,
            scoped,
            "CurrTot",
            warnings,
        )
        consumed_wh = self._counter_delta(
            all_instance,
            scoped,
            "EnrgTot",
            warnings,
        )

        mah_per_minute = None
        if (
            consumed_mah is not None
            and duration_s is not None
            and duration_s > 0
        ):
            mah_per_minute = consumed_mah / (duration_s / 60.0)

        session_configuration = self._session_configuration()

        return BatteryAnalysis(
            instance=self.instance,
            start_us=self.flight_window.start_us,
            end_us=self.flight_window.end_us,
            duration_s=duration_s,
            start_voltage=start_voltage,
            final_voltage=final_voltage,
            minimum_voltage=minimum_voltage,
            maximum_current=maximum_current,
            average_current=average_current,
            maximum_power=maximum_power,
            consumed_mah=consumed_mah,
            consumed_wh=consumed_wh,
            mah_per_minute=mah_per_minute,
            load_event=self._load_event(scoped),
            counter_warnings=warnings,
            session_configuration=session_configuration,
            bounded_load_events=self._bounded_load_events(
                all_instance,
                session_configuration,
            ),
            voltage_failsafe=assess_voltage_failsafe(
                self.flight_log, self.instance, self.flight_window,
            ),
            battery_load_response=self._load_response(all_instance),
            pilot_controlled_takeoffs=self._pilot_takeoff_measurements(all_instance),
        )

    def _pilot_takeoff_measurements(
        self, all_instance: pd.DataFrame
    ) -> list[PilotTakeoffMeasurement]:
        """Attach BAT evidence without changing legacy bounded events/history."""
        scan = detect_pilot_takeoffs(self.flight_log)
        measurements = []
        for event in scan.events:
            if event.flight_start_us != self.flight_window.start_us:
                continue
            onset = detect_pilot_load_onset(
                all_instance, self.instance, event.time_us,
                self.flight_log.get("CTUN"),
            )
            response = evaluate_load_response(
                all_instance, self.instance, onset.t0_us, self.flight_window.end_us
            )
            observation = (observe_gps_anchored_bat(
                all_instance, self.instance, event.time_us, self.flight_window.end_us
            ) if onset.t0_us is None else None)
            comparison = evaluate_observed_plateau_voltage(
                all_instance, self.instance, onset, response.t1_us,
                self.flight_window.end_us,
            )
            measurements.append(PilotTakeoffMeasurement(
                event, response, onset=onset, gps_observation=observation,
                plateau_comparison=comparison,
            ))
        return measurements

    def _load_response(self, all_instance: pd.DataFrame) -> BatteryLoadResponse | None:
        """Evaluate only independently identified AUTO takeoffs with BAT onset."""
        bounds = self._auto_takeoff_bounds()
        if not bounds:
            return None
        messages = self._time_ordered(self.flight_log.get("MSG"))
        triggers = messages[
            (messages["TimeUS"] <= bounds[0].start_us)
            & messages["Message"].astype(str).str.startswith("Triggered AUTO")
        ]
        if triggers.empty:
            return evaluate_load_response(
                all_instance, self.instance, None, self.flight_window.end_us
            )
        trigger_us = int(triggers.iloc[-1]["TimeUS"])
        t0 = detect_auto_load_onset(
            all_instance, self.instance, trigger_us, bounds[0].start_us
        )
        return evaluate_load_response(
            all_instance, self.instance, t0, self.flight_window.end_us
        )

    def _session_configuration(self) -> BatterySessionConfiguration:
        """Resolve stable primary-battery configuration from BIN PARM."""
        lookup_time_us = min(
            window.start_us for window in self.flight_log.flights
        )
        session_end_us = max(
            window.end_us for window in self.flight_log.flights
        )
        warnings: list[str] = []

        if self.instance != 0:
            warnings.append(
                "Embedded battery configuration is unavailable for "
                f"BAT instance {self.instance}."
            )
            return BatterySessionConfiguration(
                lookup_time_us=lookup_time_us,
                capacity_mah=None,
                low_voltage=None,
                critical_voltage=None,
                failsafe_voltage_source=None,
                warnings=tuple(warnings),
            )

        def stable_value(parameter_name: str) -> Optional[float]:
            history = self.flight_log.parameter_history
            value = history.value_at(parameter_name, lookup_time_us)

            if value is None or not math.isfinite(value):
                return None

            for change in history.changes.get(parameter_name, ()):
                if not (
                    lookup_time_us < change.time_us <= session_end_us
                ):
                    continue

                if change.value != value:
                    warnings.append(
                        f"{parameter_name} changes after session "
                        "configuration lookup."
                    )
                    return None

            return float(value)

        capacity_mah = stable_value("BATT_CAPACITY")
        if capacity_mah is not None and capacity_mah <= 0:
            capacity_mah = None

        low_voltage = stable_value("BATT_LOW_VOLT")
        if low_voltage is not None and low_voltage < 0:
            low_voltage = None

        critical_voltage = stable_value("BATT_CRT_VOLT")
        if critical_voltage is not None and critical_voltage < 0:
            critical_voltage = None

        return BatterySessionConfiguration(
            lookup_time_us=lookup_time_us,
            capacity_mah=capacity_mah,
            low_voltage=low_voltage,
            critical_voltage=critical_voltage,
            failsafe_voltage_source=stable_value(
                "BATT_FS_VOLTSRC"
            ),
            warnings=tuple(warnings),
        )

    def _bounded_load_events(
        self,
        all_instance: pd.DataFrame,
        session_configuration: BatterySessionConfiguration,
    ) -> list[BatteryLoadInterval]:
        bounds = self._auto_takeoff_bounds()
        bounds.extend(self._sustained_load_bounds())
        bounds.sort(key=lambda item: item.start_us)

        return [
            self._evaluate_load_interval(
                event_bounds,
                all_instance,
                session_configuration,
            )
            for event_bounds in bounds
        ]

    def _auto_takeoff_bounds(self) -> list[_BatteryLoadBounds]:
        """Return one unambiguous AUTO takeoff interval, when present."""
        mode = self._time_ordered(self.flight_log.get("MODE"))
        msg = self._time_ordered(self.flight_log.get("MSG"))

        if (
            mode.empty
            or msg.empty
            or "ModeNum" not in mode.columns
            or "Message" not in msg.columns
        ):
            return []

        mode_numbers = pd.to_numeric(
            mode["ModeNum"],
            errors="coerce",
        )
        mode = mode.loc[self._finite_mask(mode_numbers)].copy()
        mode["_mode_number"] = mode_numbers.loc[mode.index]

        prior_modes = mode[
            mode["TimeUS"] <= self.flight_window.start_us
        ]
        if (
            prior_modes.empty
            or int(prior_modes.iloc[-1]["_mode_number"]) != 13
        ):
            return []

        sequence_start_us = int(prior_modes.iloc[-1]["TimeUS"])
        for _, row in prior_modes.iloc[::-1].iterrows():
            if int(row["_mode_number"]) != 13:
                break
            sequence_start_us = int(row["TimeUS"])

        messages = msg["Message"].astype(str)
        triggers = msg[
            (msg["TimeUS"] >= sequence_start_us)
            & (msg["TimeUS"] <= self.flight_window.start_us)
            & messages.str.startswith("Triggered AUTO")
        ]
        if len(triggers) != 1:
            return []

        end_rows = mode[
            (mode["TimeUS"] > self.flight_window.start_us)
            & (mode["TimeUS"] <= self.flight_window.end_us)
            & (mode["_mode_number"] != 13)
        ]
        if end_rows.empty:
            return []

        start_us = self.flight_window.start_us
        end_us = int(end_rows.iloc[0]["TimeUS"])
        if start_us >= end_us:
            return []

        return [
            _BatteryLoadBounds(
                event_type=BatteryLoadEventType.TAKEOFF,
                takeoff_type=TakeoffType.AUTO,
                start_us=start_us,
                end_us=end_us,
            )
        ]

    def _sustained_load_bounds(self) -> list[_BatteryLoadBounds]:
        """Detect exact, unmerged continuous CTUN.ThO intervals."""
        ctun = self._time_ordered(self.flight_log.get("CTUN"))
        if ctun.empty or "ThO" not in ctun.columns:
            return []

        throttle_min = float(
            self.config.get(
                "battery_analysis.sustained_load.throttle_min_pct",
                90,
            )
        )
        minimum_duration_s = float(
            self.config.get(
                "battery_analysis.sustained_load.min_duration_s",
                8.0,
            )
        )
        if (
            not math.isfinite(throttle_min)
            or not 0 <= throttle_min <= 100
            or not math.isfinite(minimum_duration_s)
            or minimum_duration_s <= 0
        ):
            raise ValueError("Invalid sustained-load detector configuration")

        minimum_duration_us = minimum_duration_s * 1_000_000
        ctun = filter_telemetry(ctun, self.flight_window)
        throttle = pd.to_numeric(ctun["ThO"], errors="coerce")
        events: list[_BatteryLoadBounds] = []
        run_start_us = None
        run_end_us = None

        def finish_run() -> None:
            nonlocal run_start_us, run_end_us
            if (
                run_start_us is not None
                and run_end_us is not None
                and run_end_us - run_start_us >= minimum_duration_us
            ):
                events.append(
                    _BatteryLoadBounds(
                        event_type=(
                            BatteryLoadEventType.SUSTAINED_HIGH_THROTTLE
                        ),
                        takeoff_type=None,
                        start_us=run_start_us,
                        end_us=run_end_us,
                    )
                )
            run_start_us = None
            run_end_us = None

        for index, row in ctun.iterrows():
            value = throttle.loc[index]
            is_high = math.isfinite(value) and value >= throttle_min
            time_us = int(row["TimeUS"])

            if is_high:
                if run_start_us is None:
                    run_start_us = time_us
                run_end_us = time_us
            else:
                finish_run()

        finish_run()
        return events

    def _evaluate_load_interval(
        self,
        bounds: _BatteryLoadBounds,
        all_instance: pd.DataFrame,
        session_configuration: BatterySessionConfiguration,
    ) -> BatteryLoadInterval:
        bat = self._time_ordered(all_instance)
        event_bat = bat[
            (bat["TimeUS"] >= bounds.start_us)
            & (bat["TimeUS"] <= bounds.end_us)
        ]

        voltage = self._finite_numeric(bat, "Volt")
        current = self._finite_numeric(event_bat, "Curr")
        event_voltage = self._finite_numeric(event_bat, "Volt")

        before = bat[
            (bat["TimeUS"] < bounds.start_us)
            & voltage.notna()
        ]
        pre_load_voltage = (
            float(voltage.loc[before.index[-1]])
            if not before.empty
            else None
        )

        minimum_voltage = None
        current_at_minimum_voltage = None
        if not event_voltage.dropna().empty:
            minimum_index = event_voltage.idxmin()
            minimum_voltage = float(event_voltage.loc[minimum_index])
            current_at_minimum = self._finite_numeric(
                event_bat.loc[[minimum_index]],
                "Curr",
            )
            if not current_at_minimum.dropna().empty:
                current_at_minimum_voltage = float(
                    current_at_minimum.loc[minimum_index]
                )

        valid_current = current.dropna()
        peak_current = (
            float(valid_current.max())
            if not valid_current.empty
            else None
        )
        average_current = (
            float(valid_current.mean())
            if not valid_current.empty
            else None
        )

        recovery_target_us = bounds.end_us + self.RECOVERY_US
        recovery_rows = bat[
            (bat["TimeUS"] >= recovery_target_us)
            & (bat["TimeUS"] <= self.flight_window.end_us)
            & voltage.notna()
        ]
        recovery_time_us = None
        voltage_after_recovery = None
        if not recovery_rows.empty:
            recovery_index = recovery_rows.index[0]
            recovery_time_us = int(
                recovery_rows.loc[recovery_index, "TimeUS"]
            )
            voltage_after_recovery = float(
                voltage.loc[recovery_index]
            )

        voltage_sag = self._difference(
            pre_load_voltage,
            minimum_voltage,
        )
        voltage_recovery = self._difference(
            voltage_after_recovery,
            minimum_voltage,
        )

        low_voltage_margin = None
        critical_voltage_margin = None
        if session_configuration.raw_voltage_margins_supported:
            if (
                minimum_voltage is not None
                and session_configuration.low_voltage is not None
                and session_configuration.low_voltage > 0
            ):
                low_voltage_margin = (
                    minimum_voltage
                    - session_configuration.low_voltage
                )
            if (
                minimum_voltage is not None
                and session_configuration.critical_voltage is not None
                and session_configuration.critical_voltage > 0
            ):
                critical_voltage_margin = (
                    minimum_voltage
                    - session_configuration.critical_voltage
                )

        throttle = self._time_ordered(self.flight_log.get("CTUN"))
        if not throttle.empty:
            throttle = throttle[
                (throttle["TimeUS"] >= bounds.start_us)
                & (throttle["TimeUS"] <= bounds.end_us)
            ]
        throttle_values = self._finite_numeric(throttle, "ThO").dropna()

        return BatteryLoadInterval(
            event_type=bounds.event_type,
            takeoff_type=bounds.takeoff_type,
            flight_number=self._flight_number(),
            instance=self.instance,
            start_us=bounds.start_us,
            end_us=bounds.end_us,
            duration_s=(bounds.end_us - bounds.start_us) / 1_000_000,
            consumed_mah_at_start=self._counter_at(
                bat,
                "CurrTot",
                bounds.start_us,
            ),
            pre_load_voltage=pre_load_voltage,
            minimum_voltage=minimum_voltage,
            current_at_minimum_voltage=current_at_minimum_voltage,
            peak_current=peak_current,
            average_current=average_current,
            maximum_throttle=(
                float(throttle_values.max())
                if not throttle_values.empty
                else None
            ),
            average_throttle=(
                float(throttle_values.mean())
                if not throttle_values.empty
                else None
            ),
            voltage_sag=voltage_sag,
            recovery_time_us=recovery_time_us,
            voltage_after_recovery=voltage_after_recovery,
            voltage_recovery=voltage_recovery,
            low_voltage_margin=low_voltage_margin,
            critical_voltage_margin=critical_voltage_margin,
        )

    def _flight_number(self) -> int:
        return next(
            index
            for index, window in enumerate(self.flight_log.flights, start=1)
            if window is self.flight_window
        )

    @staticmethod
    def _finite_mask(values: pd.Series) -> pd.Series:
        return values.map(
            lambda value: pd.notna(value) and math.isfinite(value)
        )

    @classmethod
    def _finite_numeric(
        cls,
        data: pd.DataFrame,
        column: str,
    ) -> pd.Series:
        if column not in data.columns:
            return pd.Series(index=data.index, dtype=float)

        values = pd.to_numeric(data[column], errors="coerce")
        return values.where(cls._finite_mask(values))

    @classmethod
    def _time_ordered(cls, data: pd.DataFrame) -> pd.DataFrame:
        if data is None or data.empty or "TimeUS" not in data.columns:
            return pd.DataFrame()

        times = pd.to_numeric(data["TimeUS"], errors="coerce")
        result = data.loc[cls._finite_mask(times)].copy()
        result["TimeUS"] = times.loc[result.index]
        return result.sort_values("TimeUS", kind="stable")

    @classmethod
    def _counter_at(
        cls,
        data: pd.DataFrame,
        column: str,
        time_us: int,
    ) -> Optional[float]:
        counter = cls._finite_numeric(data, column)
        rows = data[
            (data["TimeUS"] <= time_us)
            & counter.notna()
        ]
        if rows.empty:
            return None

        values = counter.loc[rows.index]
        if (values.diff().dropna() < 0).any():
            return None

        return float(values.iloc[-1])

    @staticmethod
    def _difference(
        minuend: Optional[float],
        subtrahend: Optional[float],
    ) -> Optional[float]:
        if minuend is None or subtrahend is None:
            return None
        return minuend - subtrahend

    def _instance_rows(self, bat: pd.DataFrame) -> pd.DataFrame:
        instances = pd.to_numeric(bat["Inst"], errors="coerce")
        return bat.loc[instances == self.instance].copy()

    def _duration_s(self) -> Optional[float]:
        duration_s = (
            self.flight_window.end_us - self.flight_window.start_us
        ) / 1_000_000

        return duration_s if duration_s > 0 else None

    @staticmethod
    def _numeric(data: pd.DataFrame, column: str) -> pd.Series:
        if column not in data.columns:
            return pd.Series(dtype=float)

        return pd.to_numeric(
            data[column],
            errors="coerce",
        ).dropna()

    def _first_value(
        self,
        data: pd.DataFrame,
        column: str,
    ) -> Optional[float]:
        values = self._numeric(data, column)
        return float(values.iloc[0]) if not values.empty else None

    def _last_value(
        self,
        data: pd.DataFrame,
        column: str,
    ) -> Optional[float]:
        values = self._numeric(data, column)
        return float(values.iloc[-1]) if not values.empty else None

    def _minimum_value(
        self,
        data: pd.DataFrame,
        column: str,
    ) -> Optional[float]:
        values = self._numeric(data, column)
        return float(values.min()) if not values.empty else None

    def _maximum_value(
        self,
        data: pd.DataFrame,
        column: str,
    ) -> Optional[float]:
        values = self._numeric(data, column)
        return float(values.max()) if not values.empty else None

    def _mean_value(
        self,
        data: pd.DataFrame,
        column: str,
    ) -> Optional[float]:
        values = self._numeric(data, column)
        return float(values.mean()) if not values.empty else None

    def _maximum_power(
        self,
        data: pd.DataFrame,
    ) -> Optional[float]:
        if not {"Volt", "Curr"}.issubset(data.columns):
            return None

        voltage = pd.to_numeric(data["Volt"], errors="coerce")
        current = pd.to_numeric(data["Curr"], errors="coerce")

        power = (voltage * current).dropna()

        return float(power.max()) if not power.empty else None

    def _counter_delta(
        self,
        all_instance: pd.DataFrame,
        scoped: pd.DataFrame,
        column: str,
        warnings: list[str],
    ) -> Optional[float]:
        if column not in all_instance.columns:
            warnings.append(f"{column} is unavailable.")
            return None

        all_values = all_instance.copy()
        all_values["_counter"] = pd.to_numeric(
            all_values[column],
            errors="coerce",
        )

        all_values = (
            all_values
            .dropna(subset=["_counter"])
            .sort_values("TimeUS")
        )

        scoped_values = all_values[
            (
                all_values["TimeUS"]
                >= self.flight_window.start_us
            )
            &
            (
                all_values["TimeUS"]
                <= self.flight_window.end_us
            )
        ]

        if scoped_values.empty:
            warnings.append(
                f"{column} has no valid in-window samples."
            )
            return None

        # The counter baseline is the last valid sample strictly BEFORE
        # the FlightWindow. A sample exactly at the window start belongs
        # to the flight and must not be used as the baseline.
        baseline_rows = all_values[
            all_values["TimeUS"] < self.flight_window.start_us
        ]

        if baseline_rows.empty:
            baseline = float(
                scoped_values["_counter"].iloc[0]
            )

            warnings.append(
                f"{column} baseline unavailable before FlightWindow "
                "start; using first in-window sample."
            )
        else:
            baseline = float(
                baseline_rows["_counter"].iloc[-1]
            )

        counter_values = pd.concat(
            [
                pd.Series([baseline]),
                scoped_values["_counter"].reset_index(
                    drop=True
                ),
            ],
            ignore_index=True,
        )

        if (
            counter_values.diff().dropna() < 0
        ).any():
            warnings.append(
                f"{column} is non-monotonic or reset in "
                "FlightWindow."
            )
            return None

        return float(
            scoped_values["_counter"].iloc[-1] - baseline
        )

    def _load_event(
        self,
        scoped: pd.DataFrame,
    ) -> Optional[BatteryLoadEvent]:
        if "Curr" not in scoped.columns:
            return None

        current = pd.to_numeric(
            scoped["Curr"],
            errors="coerce",
        )

        if current.dropna().empty:
            return None

        peak_index = current.idxmax()
        peak = scoped.loc[peak_index]

        peak_time = int(peak["TimeUS"])
        peak_current = float(current.loc[peak_index])

        before = scoped[
            scoped["TimeUS"] < peak_time
        ]

        voltage_before = self._last_value(
            before,
            "Volt",
        )

        minimum_voltage = self._numeric(
            scoped.loc[[peak_index]],
            "Volt",
        )

        minimum_voltage = (
            float(minimum_voltage.iloc[0])
            if not minimum_voltage.empty
            else None
        )

        voltage_sag = None

        if (
            voltage_before is not None
            and minimum_voltage is not None
        ):
            voltage_sag = (
                voltage_before - minimum_voltage
            )

        sag_per_ampere = None

        if (
            voltage_sag is not None
            and peak_current > 0
        ):
            sag_per_ampere = (
                voltage_sag / peak_current
            )

        recovery_target = (
            peak_time + self.RECOVERY_US
        )

        recovery_rows = scoped[
            scoped["TimeUS"] >= recovery_target
        ]

        voltage_after_recovery = self._first_value(
            recovery_rows,
            "Volt",
        )

        voltage_recovery = None

        if (
            voltage_after_recovery is not None
            and minimum_voltage is not None
        ):
            voltage_recovery = (
                voltage_after_recovery - minimum_voltage
            )

        return BatteryLoadEvent(
            time_us=peak_time,
            current=peak_current,
            voltage_before=voltage_before,
            minimum_voltage=minimum_voltage,
            voltage_sag=voltage_sag,
            sag_per_ampere=sag_per_ampere,
            voltage_after_recovery=voltage_after_recovery,
            voltage_recovery=voltage_recovery,
        )
