"""Explicit, standalone v2 history recorder; never called by normal ingestion."""

from pathlib import Path

from .battery import BatteryLoadEventType, BatteryProcessor, TakeoffType
from .battery_pack_history import BatteryPackHistoryError
from .battery_pack_history_v2 import (
    SEMANTICS,
    BatteryPackHistoryV2Store,
    BatteryPackObservationV2,
    LoadEvidenceV2,
    PlateauEvidenceV2,
    physical_event_id_for,
    v2_observation_id_for,
)
from .battery_pack_store import fingerprint_log
from .gps_time import gps_time_at


class BatteryPackHistoryV2Recorder:
    """Build all supported observations before writing one v2 batch."""

    def __init__(self, config):
        self.config = config

    def record(self, flight_log, log_path, source_sha256, pack_id, store):
        if not isinstance(store, BatteryPackHistoryV2Store):
            raise BatteryPackHistoryError("An explicit v2 history store is required.")
        path = Path(log_path)
        if fingerprint_log(path) != source_sha256:
            raise BatteryPackHistoryError("Source BIN SHA-256 does not match its contents.")
        if not isinstance(pack_id, str) or not pack_id.strip() or pack_id != pack_id.strip():
            raise BatteryPackHistoryError("A normalized Pack ID is required.")
        if not flight_log.flights:
            return 0
        probe = BatteryProcessor(flight_log, flight_log.flights[0], 0, config=self.config)
        candidates = []
        for flight_number, window in enumerate(flight_log.flights, 1):
            for instance in probe.available_instances():
                analysis = BatteryProcessor(flight_log, window, instance,
                                            config=self.config).analyse()
                if analysis is None:
                    continue
                auto = [event for event in analysis.bounded_load_events
                        if event.event_type is BatteryLoadEventType.TAKEOFF
                        and event.takeoff_type is TakeoffType.AUTO]
                if auto and _gps_row_at_window_start(flight_log, window.start_us):
                    for event in auto:
                        if event.instance == instance and event.flight_number == flight_number:
                            candidates.append(_observation(
                                flight_log, path, source_sha256, pack_id, window,
                                flight_number, instance, "AUTO", "AUTO", window.start_us,
                                analysis.battery_load_response, None, None,
                            ))
                for measurement in analysis.pilot_controlled_takeoffs:
                    event = measurement.event
                    if event.flight_start_us != window.start_us or event.mode_name not in ("MANUAL", "FBWA"):
                        continue
                    candidates.append(_observation(
                        flight_log, path, source_sha256, pack_id, window,
                        flight_number, instance, "PILOT_CONTROLLED", event.mode_name,
                        event.time_us, measurement.response, measurement.plateau_comparison,
                        measurement.gps_observation,
                    ))
        # A caller may have retained this store while its file changed on disk.
        # Reject malformed or unsupported existing history before any write.
        store._load()
        return store.add_observations(candidates)


def _gps_row_at_window_start(flight_log, stamp):
    gps = flight_log.get("GPS")
    return not gps.empty and "TimeUS" in gps.columns and (gps["TimeUS"] == stamp).any()


def _load_evidence(response, gps_observation=None):
    if response is None:
        peak = getattr(gps_observation, "raw_peak_current_a", None)
        minimum = getattr(gps_observation, "minimum_voltage_v", None)
        current = getattr(gps_observation, "current_at_minimum_a", None)
        return LoadEvidenceV2(
            "partial" if any(value is not None for value in (peak, minimum, current))
            else "unavailable", None,
            "unavailable", None, None, "unavailable", None,
            peak, minimum, current, "partial" if minimum is not None else "unavailable",
            None, None, None,
            "unavailable", None, None, None,
            ("BAT load response unavailable.",
             *((gps_observation.status,) if gps_observation is not None else ())),
        )
    t0 = response.t0_us
    raw_peak = (response.raw_peak_current_a if response.raw_peak_current_a is not None
                else getattr(gps_observation, "raw_peak_current_a", None))
    minimum = (response.minimum_voltage_v if response.minimum_voltage_v is not None
               else getattr(gps_observation, "minimum_voltage_v", None))
    current_at_minimum = (response.current_at_minimum_a if response.current_at_minimum_a is not None
                          else getattr(gps_observation, "current_at_minimum_a", None))
    reference = (t0 is not None and response.reference_current_a is not None
                 and response.threshold_current_a is not None)
    t1 = reference and response.t1_us is not None
    strict = (t0 is not None and response.baseline_voltage_v is not None
              and response.baseline_current_a is not None
              and response.minimum_voltage_v is not None
              and response.voltage_drop_v is not None)
    if all(value is not None for value in (response.follow_up_time_us,
                                           response.follow_up_voltage_v,
                                           response.follow_up_current_a)):
        follow_up = (
            f"Observed five-second follow-up at {response.follow_up_time_us} us: "
            f"{response.follow_up_voltage_v:g} V, {response.follow_up_current_a:g} A; "
            "low-load recovery is not independently qualified."
        )
    else:
        follow_up = "Low-load recovery is not independently qualified; follow-up unavailable."
    limitations = (
        response.status or "Battery load evidence incomplete.",
        *(reason for condition, reason in (
            (t0 is None, "Qualified BAT onset unavailable."),
            (not reference, "High-load current reference unavailable."),
            (not t1, "Confirmed 80% current reduction unavailable."),
            (not strict, "Qualified low-current voltage baseline/drop unavailable."),
        ) if condition),
        follow_up,
        *((gps_observation.status,) if t0 is None and gps_observation is not None else ()),
    )
    return LoadEvidenceV2(
        "qualified" if t0 is not None else "partial" if any(
            value is not None for value in (raw_peak, minimum, current_at_minimum))
        else "unavailable", t0,
        "qualified" if reference else "partial" if t0 is not None else "unavailable",
        response.reference_current_a if reference else None,
        response.threshold_current_a if reference else None,
        "qualified" if t1 else "partial" if reference else "unavailable",
        response.t1_us if t1 else None,
        raw_peak, minimum,
        current_at_minimum,
        "qualified" if strict else "partial" if minimum is not None
        else "unavailable",
        response.baseline_voltage_v if strict else None,
        response.baseline_current_a if strict else None,
        response.voltage_drop_v if strict else None,
        "unavailable", None, None, None,
        limitations,
    )


def _plateau_evidence(comparison):
    if comparison is None:
        return PlateauEvidenceV2("unavailable", *([None] * 10),
                                 "No established plateau evaluator for this event.")
    qualified = comparison.status.startswith("Qualified")
    if not qualified:
        return PlateauEvidenceV2("unavailable", *([None] * 10), comparison.status)
    return PlateauEvidenceV2(
        "qualified", comparison.pre_start_us, comparison.pre_end_us,
        comparison.pre_voltage_v, comparison.pre_current_a,
        comparison.loaded_start_us, comparison.loaded_end_us,
        comparison.loaded_voltage_v, comparison.loaded_current_a,
        comparison.voltage_change_v, comparison.current_change_a, None,
    )


def _observation(flight_log, path, source_sha256, pack_id, window, flight_number,
                 instance, takeoff_type, mode, logged_takeoff_us, response, comparison,
                 gps_observation):
    identity = physical_event_id_for(
        source_sha256=source_sha256, battery_instance=instance,
        flight_start_us=window.start_us, flight_end_us=window.end_us,
        logged_takeoff_us=logged_takeoff_us,
    )
    gps = gps_time_at(flight_log, logged_takeoff_us)
    observation = BatteryPackObservationV2(
        2, SEMANTICS, identity, v2_observation_id_for(identity), source_sha256,
        path.name, pack_id, instance, flight_number, window.start_us, window.end_us,
        takeoff_type, mode, logged_takeoff_us,
        gps.utc_isoformat() if gps is not None else None,
        gps.gps_anchor_week if gps is not None else None,
        gps.gps_anchor_week_ms if gps is not None else None,
        gps.gps_anchor_time_us if gps is not None else None,
        gps.gps_instance if gps is not None else None,
        gps.gps_utc_offset_seconds if gps is not None else None,
        True, _load_evidence(response, gps_observation), _plateau_evidence(comparison),
    )
    observation.validate()
    return observation
