from analyses.log_selector import select_log_input
from core.battery import (
    BatteryAnalysis,
    BatteryLoadEventType,
    BatteryProcessor,
)
from core.battery_failsafe import VoltageFailsafeAssessment
from core.battery_pack_history import (
    BatteryPackHistoryError,
    BatteryPackHistoryStore,
)
from core.battery_pack_history_recorder import BatteryPackHistoryRecorder
from core.battery_pack_store import (
    BatteryPackStore,
    BatteryPackStoreError,
    LogPackState,
    fingerprint_log,
)
from core.config import Config
from core.log_reader import (
    FlightReader,
    UnsupportedFirmwareError,
)
from core.time import format_time, format_time_us


def _format_value(value, suffix="", decimals=2):
    """Format an optional numeric measurement."""

    if value is None:
        return "Unavailable"

    return f"{value:.{decimals}f}{suffix}"


def _format_duration(seconds):
    """Format an optional duration as mm:ss."""

    if seconds is None:
        return "Unavailable"

    total_seconds = int(round(seconds))
    minutes, seconds = divmod(total_seconds, 60)

    return f"{minutes:02d}:{seconds:02d}"


def _format_threshold(value):
    if value is None:
        return "Unavailable"
    if value == 0:
        return "Disabled"
    return f"{value:.2f} V"


def format_bounded_load_events(events) -> str:
    """Return the existing bounded-load-event presentation."""
    lines = ["BOUNDED LOAD EVENTS (legacy interval calculations; load at +5 s unverified)"]
    if not events:
        lines.extend(("", "No bounded load events detected."))
        return "\n".join(lines)

    for index, event in enumerate(events, start=1):
        lines.extend(("", f"{index}. {event.event_type.value}"))
        if (
            event.event_type == BatteryLoadEventType.TAKEOFF
            and event.takeoff_type is not None
        ):
            lines.append(f"   Context              {event.takeoff_type.value}")
        lines.extend(
            (
                "   Time                 "
                f"{format_time_us(event.start_us)} -> "
                f"{format_time_us(event.end_us)}",
                "   Duration             "
                f"{_format_value(event.duration_s, ' s', 3)}",
                "   Capacity used before event    "
                f"{_format_value(event.consumed_mah_at_start, ' mAh')}",
                "   Maximum throttle     "
                f"{_format_value(event.maximum_throttle, ' %')}",
                "   Average throttle     "
                f"{_format_value(event.average_throttle, ' %')}",
                "   Legacy pre-interval voltage  "
                f"{_format_value(event.pre_load_voltage, ' V')}",
                "   Minimum voltage      "
                f"{_format_value(event.minimum_voltage, ' V')}",
                "   Legacy interval voltage drop  "
                f"{_format_value(event.voltage_sag, ' V')}",
                "   Peak current         "
                f"{_format_value(event.peak_current, ' A')}",
                "   Average current      "
                f"{_format_value(event.average_current, ' A')}",
                "   Current at min V     "
                f"{_format_value(event.current_at_minimum_voltage, ' A')}",
                "   Voltage at first BAT ≥5 s after interval  "
                f"{_format_value(event.voltage_after_recovery, ' V')}",
                "   Legacy change from interval minimum (load unverified)  "
                f"{_format_value(event.voltage_recovery, ' V')}",
                "   Margin to LOW        "
                f"{_format_value(event.low_voltage_margin, ' V')}",
                "   Margin to CRITICAL   "
                f"{_format_value(event.critical_voltage_margin, ' V')}",
            )
        )
    return "\n".join(lines)


def format_voltage_failsafe_assessment(
    assessment: VoltageFailsafeAssessment | None,
) -> str:
    """Present observed battery events separately from offline voltage replay."""
    lines = ["VOLTAGE FAILSAFE ASSESSMENT"]
    if assessment is None or assessment.sample_count == 0:
        lines.extend(("", "BAT voltage evidence unavailable."))
        if assessment is not None:
            lines.extend(_format_observed_battery_failsafes(assessment))
        return "\n".join(lines)
    lines.append("")
    lines.append(
        "Offline replay of the recorded trajectory; "
        "timing is limited to BAT samples."
    )
    config = assessment.starting_configuration
    if config is not None:
        low = _format_threshold(config.low_v)
        critical = _format_threshold(config.critical_v)
        timer = "Unavailable" if config.timer_s is None else f"{config.timer_s:g} s"
        lines.append(
            f"Recorded settings at first BAT: source {config.source}, low {low}, "
            f"critical {critical}, timer {timer}, actions low/critical "
            f"{config.low_action}/{config.critical_action}."
        )
    if config is not None:
        def capacity_threshold(value):
            if value is None:
                return "unavailable"
            return "disabled" if value <= 0 else f"{value:g} mAh"

        low_mah = capacity_threshold(config.low_mah)
        critical_mah = capacity_threshold(config.critical_mah)
        lines.append(
            f"Capacity failsafe thresholds: low {low_mah}, "
            f"critical {critical_mah}."
        )
    if assessment.compensation_unavailable:
        lines.append(
            "Compensated voltage partly unavailable: "
            + (assessment.compensation_reason or "invalid telemetry")
        )
    if assessment.raw_unavailable:
        lines.append("Raw voltage partly unavailable: missing or invalid BAT.Volt.")
    if assessment.sampling_gaps:
        lines.append("BAT sample gaps: qualification is unknown across gaps.")
    for source in ("raw", "compensated"):
        incomplete = (
            assessment.sampling_gaps
            or (source == "raw" and assessment.raw_unavailable)
            or (source == "compensated" and assessment.compensation_unavailable)
        )
        for stage in ("low", "critical"):
            events = [
                event for event in assessment.excursions
                if event.source == source and event.stage == stage
            ]
            qualifying = [
                event for event in events if event.first_qualification_us is not None
            ]
            outside = [
                event for event in events if event.qualification_outside_window
            ]
            longest = max(events, key=lambda event: event.duration_s, default=None)
            if incomplete and not qualifying:
                qualification_text = "qualification indeterminate (0 observed)"
            elif incomplete:
                qualification_text = (
                    f"at least {len(qualifying)} qualifying; "
                    "unknown over missing data"
                )
            else:
                qualification_text = f"{len(qualifying)} qualifying"
            summary = (
                f"{source.title()} {stage}: {len(events)} excursions, "
                f"{qualification_text}"
            )
            if outside:
                summary += (
                    f"; {len(outside)} qualification(s) outside selected flight"
                )
            if longest is not None:
                summary += (
                    f"; longest {longest.duration_s:.1f} s "
                    f"({format_time_us(longest.start_us)}-"
                    f"{format_time_us(longest.end_us)})"
                )
            lines.append(summary)
            for event in qualifying:
                config = event.configuration
                role = (
                    "recorded source" if event.selected_source
                    else "alternative source"
                )
                threshold = config.low_v if stage == "low" else config.critical_v
                action = config.low_action if stage == "low" else config.critical_action
                current = _format_value(event.maximum_current_a, " A")
                consumed = _format_value(event.consumed_mah_at_end, " mAh", 0)
                session = (
                    event.armed_session
                    if event.armed_session is not None
                    else "unknown/disarmed"
                )
                lines.append(
                    f"  Replay ({role}): {format_time_us(event.start_us)}-"
                    f"{format_time_us(event.end_us)}, first qualifies "
                    f"{format_time_us(event.first_qualification_us)}; "
                    f"min {event.minimum_v:.3f} V, max {current}, "
                    f"consumed at end {consumed}; threshold {threshold:.2f} V / "
                    f"{config.timer_s:g} s, source setting {config.source}, "
                    f"action {action}, armed session {session}"
                    f"{'; gap follows' if event.gap_after else ''}"
                )
    lines.extend(_format_observed_battery_failsafes(assessment))
    return "\n".join(lines)


def _format_observed_battery_failsafes(assessment: VoltageFailsafeAssessment) -> list[str]:
    lines = []
    if not assessment.observed:
        lines.append("Observed battery failsafe messages: none in this flight window.")
    for observed in assessment.observed:
        label = (
            "Battery-low message with correlated RTL (MODE reason 4)"
            if observed.stage == "low" and observed.mode_number == 11
            and observed.mode_reason == 4
            else "Observed battery message"
        )
        line = f"{label} at {format_time_us(observed.time_us)}: {observed.message}"
        if observed.mode_time_us is not None:
            line += (
                f"; nearby MODE {observed.mode_number} reason "
                f"{observed.mode_reason} at "
                f"{format_time_us(observed.mode_time_us)} "
                "(temporal association, not proof of causation)"
            )
        lines.append(line)
    return lines


def format_load_response_measurement(response) -> str:
    """Present the shared Slice 1 BAT response for either takeoff context."""
    lines = [response.status]
    if response.t0_us is not None:
        lines.append(f"T0 load onset: {format_time_us(response.t0_us)}")
    if response.raw_peak_current_a is not None:
        lines.append(f"Raw peak current: {_format_value(response.raw_peak_current_a, ' A')}")
    if response.minimum_voltage_v is not None:
        lines.append(
            f"Minimum voltage: {_format_value(response.minimum_voltage_v, ' V')} "
            f"at {_format_value(response.current_at_minimum_a, ' A')}"
        )
    if response.observation_end_us is not None:
        lines.append(f"Observation through: {format_time_us(response.observation_end_us)}")
    if response.reference_current_a is not None:
        lines.extend((
            f"Smoothed reference current: {response.reference_current_a:.2f} A",
            f"80% current threshold: {response.threshold_current_a:.2f} A",
            f"Low-current baseline: {_format_value(response.baseline_voltage_v, ' V')} "
            f"at {_format_value(response.baseline_current_a, ' A')}",
            f"T1 confirmed reduction: "
            f"{format_time_us(response.t1_us) if response.t1_us is not None else 'Unavailable'}",
            f"Confirmed reduction duration: "
            f"{_format_value((response.t1_us - response.t0_us) / 1_000_000, ' s') if response.t1_us is not None else 'Unavailable'}",
            f"Voltage drop from baseline: {_format_value(response.voltage_drop_v, ' V')}",
            f"Voltage/current at first BAT sample ≥5 s after observation: "
            f"{format_time_us(response.follow_up_time_us) if response.follow_up_time_us is not None else 'Unavailable'}; "
            f"{_format_value(response.follow_up_voltage_v, ' V')} / "
            f"{_format_value(response.follow_up_current_a, ' A')} "
            "(may still be loaded; not unloaded recovery)",
        ))
    return "\n".join(lines)


def format_battery_report(
    log_path,
    flight_window,
    analysis: BatteryAnalysis | None,
    pack_id=None,
) -> str:
    """Return the existing Battery Analysis presentation for one instance."""
    lines = [
        "BATTERY ANALYSIS",
        "=" * 70,
        f"Log    : {log_path.name}",
        (
            "Window : "
            f"{format_time(flight_window.start_us)}"
            " -> "
            f"{format_time(flight_window.end_us)}"
        ),
    ]
    if analysis is None:
        lines.extend(("", "No valid battery analysis is available."))
        return "\n".join(lines)

    lines.append(f"Battery instance : {analysis.instance}")
    configuration = analysis.session_configuration
    if pack_id is not None:
        lines.append(f"Pack ID          : {pack_id}")
    if configuration is not None:
        lines.extend(
            (
                "Capacity         : "
                f"{_format_value(configuration.capacity_mah, ' mAh', 0)}",
                "Low voltage      : "
                f"{_format_threshold(configuration.low_voltage)}",
                "Critical voltage : "
                f"{_format_threshold(configuration.critical_voltage)}",
            )
        )

    lines.extend(
        (
            "",
            "Flight duration       " f"{_format_duration(analysis.duration_s)}",
            "Start voltage         "
            f"{_format_value(analysis.start_voltage, ' V')}",
            "Final voltage         "
            f"{_format_value(analysis.final_voltage, ' V')}",
            "Minimum voltage       "
            f"{_format_value(analysis.minimum_voltage, ' V')}",
            "",
            "Maximum current       "
            f"{_format_value(analysis.maximum_current, ' A')}",
            "Average current       "
            f"{_format_value(analysis.average_current, ' A')}",
            "Maximum power         "
            f"{_format_value(analysis.maximum_power, ' W')}",
            "Energy consumed       "
            f"{_format_value(analysis.consumed_wh, ' Wh')}",
            "Capacity consumed     "
            f"{_format_value(analysis.consumed_mah, ' mAh')}",
            "Consumption rate      "
            f"{_format_value(analysis.mah_per_minute, ' mAh/min')}",
            "",
            "HIGHEST-LOAD EVENT (legacy adjacent-sample calculation)",
        )
    )

    event = analysis.load_event
    if event is None:
        lines.extend(("", "No valid load event is available."))
    else:
        lines.extend(
            (
                "",
                f"Time                  {format_time_us(event.time_us)}",
                "Current               "
                f"{_format_value(event.current, ' A')}",
                "Legacy preceding BAT voltage  "
                f"{_format_value(event.voltage_before, ' V')}",
                "Minimum voltage       "
                f"{_format_value(event.minimum_voltage, ' V')}",
                "Legacy adjacent-sample voltage drop  "
                f"{_format_value(event.voltage_sag, ' V')}",
                "Legacy V/A estimate (not cell resistance)  "
                f"{_format_value(event.sag_per_ampere, ' V/A')}",
                "Voltage at first BAT ≥5 s after event  "
                f"{_format_value(event.voltage_after_recovery, ' V')}",
                "Legacy change from minimum (load unverified)  "
                f"{_format_value(event.voltage_recovery, ' V')}",
            )
        )

    if analysis.counter_warnings:
        lines.extend(("", "COUNTER WARNINGS"))
        for warning in analysis.counter_warnings:
            lines.extend(("", f"- {warning}"))

    lines.extend(("", format_bounded_load_events(analysis.bounded_load_events)))
    response = getattr(analysis, "battery_load_response", None)
    if response is not None:
        lines.extend(("", "BATTERY LOAD RESPONSE (read-only, AUTO context)",
                      format_load_response_measurement(response)))
    pilot_takeoffs = getattr(analysis, "pilot_controlled_takeoffs", ())
    if pilot_takeoffs:
        lines.extend(("", "PILOT-CONTROLLED TAKEOFFS (read-only; no history write)"))
        for number, measurement in enumerate(pilot_takeoffs, start=1):
            evidence = measurement.event
            lines.extend((
                "",
                (f"{number}. PILOT_CONTROLLED / {evidence.mode_name} "
                 f"at {format_time_us(evidence.time_us)}"),
                (f"Ground evidence: GPS {evidence.ground_speed_m_s:.2f} m/s; "
                 f"prior low speed at {format_time_us(evidence.ground_time_us)}; "
                 f"POS climb {evidence.climb_m:.1f} m by "
                 f"{format_time_us(evidence.climb_time_us)}; "
                 f"CTUN throttle up to {evidence.throttle_pct:.1f}%."),
                (f"STAT.isFlying before event: "
                 f"{evidence.stat_flying_before if evidence.stat_flying_before is not None else 'Unavailable'} "
                 "(supporting only)."),
                f"Ground-state basis: {evidence.ground_evidence}",
                measurement.onset.status if measurement.onset is not None else
                "Pilot BAT onset evidence unavailable.",
                "Takeoff confirmation is independent of BAT T0; "
                "no T0-based load response is inferred when onset is unavailable."
                if measurement.response.t0_us is None else
                "BAT T0 established separately from takeoff confirmation.",
                format_load_response_measurement(measurement.response),
            ))
            onset = measurement.onset
            if onset is not None and onset.t0_us is not None:
                lines.extend((
                    ("Pilot onset evidence: BAT current "
                     f"{_format_value(onset.baseline_current_a, ' A')} at "
                     f"{format_time_us(onset.baseline_start_us)}–"
                     f"{format_time_us(onset.baseline_end_us)}; "
                     f"crossed {_format_value(onset.onset_threshold_a, ' A')} "
                     f"at {format_time_us(onset.t0_us)}; "
                     f"median {_format_value(onset.confirmed_current_a, ' A')} "
                     f"through {format_time_us(onset.confirmation_end_us)}; "
                     f"CTUN throttle {_format_value(onset.throttle_pct, '%')}."),
                ))
            observation = measurement.gps_observation
            comparison = measurement.plateau_comparison
            if comparison is not None:
                lines.extend(("", "OBSERVED PLATEAU VOLTAGE COMPARISON"))
                if comparison.voltage_change_v is None:
                    lines.append(comparison.status)
                else:
                    lines.extend((
                        (f"Pre-onset: {_format_value(comparison.pre_voltage_v, ' V')} at "
                         f"{_format_value(comparison.pre_current_a, ' A')}; "
                         f"{format_time_us(comparison.pre_start_us)}–"
                         f"{format_time_us(comparison.pre_end_us)}."),
                        (f"Loaded: {_format_value(comparison.loaded_voltage_v, ' V')} at "
                         f"{_format_value(comparison.loaded_current_a, ' A')}; "
                         f"{format_time_us(comparison.loaded_start_us)}–"
                         f"{format_time_us(comparison.loaded_end_us)}."),
                        (f"Observed plateau voltage change: "
                         f"{_format_value(comparison.voltage_change_v, ' V')}; "
                         f"median current change: "
                         f"{_format_value(comparison.current_change_a, ' A')}."),
                        (f"Pre-onset interval to T0: {comparison.pre_to_t0_us / 1_000_000:.2f} s; "
                         f"T0 to loaded interval: {comparison.t0_to_loaded_us / 1_000_000:.2f} s."),
                        comparison.status,
                    ))
            if observation is not None:
                lines.extend((
                    "GPS-ANCHORED BAT OBSERVATION (separate from T0-based response)",
                    (f"Interval: {format_time_us(observation.start_us)} to "
                     f"{format_time_us(observation.end_us)}; "
                     f"raw peak current {_format_value(observation.raw_peak_current_a, ' A')}; "
                     f"minimum voltage {_format_value(observation.minimum_voltage_v, ' V')} "
                     f"at {_format_value(observation.current_at_minimum_a, ' A')}."),
                    observation.status,
                ))
    lines.extend((
        "", format_voltage_failsafe_assessment(
            getattr(analysis, "voltage_failsafe", None)
        ),
    ))
    if configuration is not None and configuration.warnings:
        lines.extend(("", "CONFIGURATION WARNINGS"))
        for warning in configuration.warnings:
            lines.extend(("", f"- {warning}"))
    return "\n".join(lines)


class BatteryPackManagementPresentation:
    """Manage persistent physical battery Pack IDs."""

    def __init__(self, pack_store=None):
        self.pack_store = pack_store

    def run(self):
        try:
            store = self.pack_store or BatteryPackStore()
        except (BatteryPackStoreError, OSError) as exc:
            print()
            print(f"Battery pack management unavailable: {exc}")
            return

        while True:
            print()
            print("Battery Pack Management")
            print("=======================")
            print()
            print("1. Rename Pack ID")
            print("2. Change log pack assignment")
            print("3. Archive Pack ID")
            print("4. Restore Pack ID")
            print("5. Delete Pack ID")
            print("0. Back")

            choice = input("\nSelection: ").strip()

            if choice == "0":
                return

            if choice == "1":
                self._rename_pack(store)
                continue

            if choice == "2":
                self._change_log_pack_assignment(store)
                continue

            if choice in ("3", "4", "5"):
                choices = (store.active_pack_ids if choice == "3" else
                           store.archived_pack_ids if choice == "4" else store.pack_ids)
                if not choices:
                    print("No eligible Battery Pack IDs.")
                    continue
                pack_id = self._select_pack(choices)
                if pack_id is None:
                    continue
                try:
                    if choice == "3":
                        store.archive_pack(pack_id)
                    elif choice == "4":
                        store.restore_pack(pack_id)
                    else:
                        history = BatteryPackHistoryStore()
                        plan = store.deletion_plan(pack_id, history)
                        confirmation = input(
                            f"Permanently delete Pack ID {pack_id}, change "
                            f"{len(plan.log_fingerprints)} associated BIN logs to "
                            "Not tracked, and delete "
                            f"{len(plan.observation_ids)} history observations? "
                            "Original BIN files remain untouched. (yes/no): "
                        ).strip()
                        if confirmation != "yes":
                            continue
                        store.delete_pack(pack_id, history, plan)
                except (BatteryPackStoreError, BatteryPackHistoryError, OSError) as exc:
                    print(exc)
                continue

            print("Invalid selection.")

    def _rename_pack(self, store):
        if not store.pack_ids:
            print()
            print("No known Battery Pack IDs.")
            return

        pack_id = self._select_pack(store.pack_ids)
        if pack_id is None:
            return

        print()
        print(f"Current Pack ID: {pack_id}")
        new_pack_id = input("New Pack ID: ").strip()

        if new_pack_id == pack_id:
            print()
            print("Pack ID unchanged.")
            return

        try:
            store.rename_pack(pack_id, new_pack_id)
        except BatteryPackStoreError as exc:
            print()
            print(exc)
            return
        except OSError as exc:
            print()
            print(f"Unable to rename Battery Pack ID: {exc}")
            print("Persistent pack data was not changed.")
            return

        print()
        print(f"Renamed Pack ID: {pack_id} -> {new_pack_id.strip()}")

    def _change_log_pack_assignment(self, store):
        """Change the physical Pack ID associated with one source BIN."""
        selected_logs = select_log_input()
        if selected_logs is None:
            return

        log_path = selected_logs[0]

        try:
            fingerprint = fingerprint_log(log_path)
            association = store.association_for(fingerprint)
        except (BatteryPackStoreError, OSError) as exc:
            print()
            print(f"Unable to identify source log: {exc}")
            return

        print()
        print(f"Source log: {log_path.name}")

        if association.state is LogPackState.TRACKED:
            print(f"Current Pack ID: {association.pack_id}")
        elif association.state is LogPackState.NOT_TRACKED:
            print("Current Pack ID: not tracked")
        else:
            print("Current Pack ID: unseen")

        while True:
            print()
            if store.active_pack_ids:
                print("1. Select existing pack")
                print("2. Create new pack")
            else:
                print("1. Create new pack")
            print("0. Back")

            choice = input("\nSelection: ").strip()

            if choice == "0":
                return

            if store.active_pack_ids and choice == "1":
                pack_id = self._select_pack(store.active_pack_ids)
                if pack_id is None:
                    continue

                if (
                    association.state is LogPackState.TRACKED
                    and association.pack_id == pack_id
                ):
                    print()
                    print("Pack assignment unchanged.")
                    return

                try:
                    store.associate(fingerprint, pack_id, log_path.name)
                except BatteryPackStoreError as exc:
                    print()
                    print(exc)
                    return
                except OSError as exc:
                    print()
                    print(f"Unable to change Pack ID assignment: {exc}")
                    print("Persistent pack data was not changed.")
                    return

                print()
                print(f"Pack assignment changed to: {pack_id}")
                return

            if choice == ("2" if store.active_pack_ids else "1"):
                pack_id = input("\nNew Pack ID: ").strip()

                try:
                    store.create_and_associate(fingerprint, pack_id, log_path.name)
                except BatteryPackStoreError as exc:
                    print()
                    print(exc)
                    continue
                except OSError as exc:
                    print()
                    print(f"Unable to change Pack ID assignment: {exc}")
                    print("Persistent pack data was not changed.")
                    return

                print()
                print(f"Pack assignment changed to: {pack_id}")
                return

            print("Invalid selection.")

    @staticmethod
    def _select_pack(pack_ids):
        print()
        print("Known Battery Packs")
        print("===================")

        for index, pack_id in enumerate(pack_ids, start=1):
            print(f"{index}. {pack_id}")

        print("0. Back")

        while True:
            choice = input("\nSelection: ").strip()

            if choice == "0":
                return None

            try:
                index = int(choice)
            except ValueError:
                index = 0

            if 1 <= index <= len(pack_ids):
                return pack_ids[index - 1]

            print("Invalid selection.")


def pack_performance_observations(pack_store, history_store, pack_id):
    """Return retained observations owned by one physical pack at ingest or rename."""
    observations = []
    for observation in history_store.newest_supported_observations():
        if pack_store.history_owner_for(observation) == pack_id:
            observations.append(observation)
    return sorted(observations, key=pack_performance_observation_sort_key)


def pack_performance_event_order_key(observation):
    """Order retained events within one source session."""
    return (
        observation.event_start_us,
        observation.flight_start_us,
        observation.flight_number,
        observation.battery_instance,
        observation.event_end_us,
        observation.observation_id,
    )


def pack_performance_observation_sort_key(observation):
    """Order displayed observations identically across CLI and GUI."""
    return (
        observation.recorded_at_utc is None,
        observation.recorded_at_utc or "",
        observation.source_filename,
        observation.flight_number,
        observation.battery_instance,
        observation.event_start_us,
    )


def first_pack_takeoffs_by_session(observations):
    """Return the earliest retained AUTO event for each source BIN."""
    first_by_source = {}
    for observation in observations:
        current = first_by_source.get(observation.source_sha256)
        if current is None or pack_performance_event_order_key(
            observation
        ) < pack_performance_event_order_key(current):
            first_by_source[observation.source_sha256] = observation
    return sorted(
        first_by_source.values(), key=pack_performance_observation_sort_key
    )


def pack_performance_row(observation):
    """Return one observation's existing user-visible values."""
    date = (
        observation.recorded_at_utc[:10]
        if observation.recorded_at_utc is not None
        else "Unavailable"
    )
    return (
        date,
        observation.source_filename,
        str(observation.flight_number),
        _format_value(observation.capacity_used_mah),
        _format_value(observation.average_current_a),
        _format_value(observation.peak_current_a),
        _format_value(observation.pre_load_voltage_v),
        _format_value(observation.minimum_loaded_voltage_v),
        _format_value(observation.voltage_sag_v),
        _format_value(observation.voltage_recovery_v),
    )


def format_pack_performance_table(observations):
    """Format Pack Performance rows without changing established wording."""
    lines = []
    for index, observation in enumerate(observations, start=1):
        (
            date,
            source,
            flight,
            capacity,
            average_current,
            peak_current,
            pre_load_voltage,
            minimum_loaded_voltage,
            voltage_sag,
            voltage_recovery,
        ) = pack_performance_row(observation)
        lines.extend(
            (
                "",
                f"{index}. Date: {date} | Flight: {flight}",
                f"   Source: {source}",
                f"   Capacity used (mAh): {capacity}",
                f"   Current (A): average {average_current} | peak {peak_current}",
                "   Voltage (V): "
                f"pre-load {pre_load_voltage} | "
                f"minimum loaded {minimum_loaded_voltage}",
                f"   Voltage response (V): sag {voltage_sag} | "
                f"recovery {voltage_recovery}",
            )
        )
    return "\n".join(lines)


def format_pack_performance_report(pack_store, history_store, pack_id=None):
    """Format the complete existing Pack Performance report."""
    lines = ["PACK PERFORMANCE REPORT", "=" * 70]
    if not pack_store.pack_ids:
        lines.extend(("", "No known Battery Pack IDs."))
        return "\n".join(lines)
    if pack_id not in pack_store.pack_ids:
        raise BatteryPackStoreError(f"Unknown Pack ID: {pack_id}")

    observations = pack_performance_observations(
        pack_store, history_store, pack_id
    )
    lines.extend(("", f"Pack ID: {pack_id}"))
    if not observations:
        lines.extend(
            ("", "No stored AUTO takeoff observations for this Pack ID.")
        )
        return "\n".join(lines)

    lines.extend(
        (
            "",
            "FIRST TAKEOFF BY BATTERY SESSION",
            format_pack_performance_table(
                first_pack_takeoffs_by_session(observations)
            ),
            "",
            "ALL AUTO TAKEOFFS",
            format_pack_performance_table(observations),
        )
    )
    return "\n".join(lines)


class BatteryPackPerformancePresentation:
    """Present durable AUTO takeoff evidence for one physical battery pack."""

    def __init__(self, pack_store=None, history_store=None):
        self.pack_store = pack_store
        self.history_store = history_store

    def run(self):
        """Select a known Pack ID and render its current owned history."""
        try:
            pack_store = self.pack_store or BatteryPackStore()
            history_store = self.history_store or BatteryPackHistoryStore()
        except (BatteryPackStoreError, BatteryPackHistoryError, OSError) as exc:
            print()
            print(f"Battery Pack performance data unavailable: {exc}")
            return

        if not pack_store.pack_ids:
            print()
            print(format_pack_performance_report(pack_store, history_store))
            return

        pack_id = BatteryPackManagementPresentation._select_pack(
            pack_store.pack_ids
        )
        if pack_id is None:
            return

        print()
        print(format_pack_performance_report(pack_store, history_store, pack_id))

    @classmethod
    def _first_takeoffs_by_session(cls, observations):
        """Return the earliest retained AUTO event for each source BIN."""
        return first_pack_takeoffs_by_session(observations)

    @staticmethod
    def _event_order_key(observation):
        return pack_performance_event_order_key(observation)

    @staticmethod
    def _observation_sort_key(observation):
        return pack_performance_observation_sort_key(observation)

    @classmethod
    def _print_table(cls, observations):
        print(format_pack_performance_table(observations), end="")

    @staticmethod
    def _row(observation):
        return pack_performance_row(observation)


class BatteryAnalysisPresentation:
    """
    Present battery analysis for a selected flight and battery instance.
    """

    def __init__(
        self,
        pack_id=None,
        config=None,
        pack_store=None,
        history_store=None,
    ):
        self.pack_id = pack_id
        self.config = config or Config("Config/battery.yaml")
        self.pack_store = pack_store
        self.history_store = history_store
        self._resolved_history_context = None

    def run(self):

        self._resolved_history_context = None
        selected_logs = select_log_input()

        if selected_logs is None:
            return
        log_path = selected_logs[0]

        pack_id = self.pack_id
        if pack_id is None:
            continue_analysis, pack_id = self._resolve_pack_id(log_path)
            if not continue_analysis:
                return

        try:
            flight_log = FlightReader(
                str(log_path),
                config=self.config,
            ).read()

        except UnsupportedFirmwareError as exc:
            print()
            print("Unsupported firmware.")
            print(exc)
            return
        except OSError as exc:
            print()
            print(f"Unable to read log: {exc}")
            return

        if not flight_log.flights:
            print()
            print("No flights found.")
            return

        if self._resolved_history_context is not None:
            source_sha256, tracked_pack_id = self._resolved_history_context
            self._record_pack_history(
                flight_log,
                log_path,
                source_sha256,
                tracked_pack_id,
            )

        flight_window = self._select_flight(
            flight_log
        )

        if flight_window is None:
            return

        processor = BatteryProcessor(
            flight_log,
            flight_window,
            0,
        )

        instances = processor.available_instances()

        if not instances:
            print()
            print(
                "No battery telemetry is available "
                "for this flight."
            )
            return

        instance = self._select_instance(
            instances
        )

        if instance is None:
            return

        analysis = BatteryProcessor(
            flight_log,
            flight_window,
            instance,
            config=self.config,
        ).analyse()

        self._print_report(
            log_path,
            flight_window,
            analysis,
            pack_id,
        )

    def _resolve_pack_id(self, log_path):
        """Resolve optional Pack ID metadata for one content-identified BIN."""
        try:
            store = self.pack_store or BatteryPackStore()
            fingerprint = fingerprint_log(log_path)
            association = store.association_for(fingerprint)
        except (BatteryPackStoreError, OSError) as exc:
            print()
            print(f"Battery pack tracking unavailable: {exc}")
            print("Persistent pack data was not changed. Continuing without Pack ID.")
            return True, None

        if association.state is LogPackState.TRACKED:
            self._resolved_history_context = (
                fingerprint,
                association.pack_id,
            )
            return True, association.pack_id
        if association.state is LogPackState.NOT_TRACKED:
            return True, None
        result = self._select_pack_decision(store, fingerprint, log_path)
        if result[0] and result[1] is not None:
            self._resolved_history_context = (fingerprint, result[1])
        return result

    def _record_pack_history(
        self,
        flight_log,
        log_path,
        source_sha256,
        pack_id,
    ):
        """Harvest whole-BIN AUTO history without blocking normal analysis."""
        try:
            history_store = self.history_store or BatteryPackHistoryStore()
            BatteryPackHistoryRecorder(self.config).record(
                flight_log,
                log_path,
                source_sha256,
                pack_id,
                history_store,
            )
        except Exception as exc:  # History is optional to normal Battery Analysis.
            print()
            print(f"Battery Pack history unavailable: {exc}")
            print("Normal Battery Analysis will continue.")

    def _select_pack_decision(self, store, fingerprint, log_path):
        """Prompt once for an unseen source-log fingerprint."""
        while True:
            print()
            print("Battery Pack")
            print("============")
            print()
            if store.active_pack_ids:
                print("1. Select existing pack")
                print("2. Create new pack")
                print("3. Continue without pack tracking")
            else:
                print("No existing Pack IDs.")
                print("1. Create new pack")
                print("2. Continue without pack tracking")
            print("0. Cancel")

            choice = input("\nSelection: ").strip()
            if choice == "0":
                return False, None
            if store.active_pack_ids and choice == "1":
                pack_id = self._select_existing_pack(store.active_pack_ids)
                if pack_id is None:
                    continue
                if self._save_pack_decision(
                    lambda selected_pack_id=pack_id: store.associate(
                        fingerprint,
                        selected_pack_id,
                        log_path.name,
                    )
                ):
                    return True, pack_id
                return True, None
            if choice == ("2" if store.active_pack_ids else "1"):
                pack_id = input("\nNew Pack ID: ").strip()
                try:
                    store.create_and_associate(fingerprint, pack_id, log_path.name)
                except BatteryPackStoreError as exc:
                    print(exc)
                    continue
                except OSError as exc:
                    self._print_save_error(exc)
                    return True, None
                return True, pack_id
            if choice == ("3" if store.active_pack_ids else "2"):
                if self._save_pack_decision(
                    lambda: store.mark_not_tracked(fingerprint, log_path.name)
                ):
                    return True, None
                return True, None
            print("Invalid selection.")

    @staticmethod
    def _select_existing_pack(pack_ids):
        """Select one known physical Pack ID, or return to the decision menu."""
        print()
        print("Existing Battery Packs")
        print("======================")
        for index, pack_id in enumerate(pack_ids, start=1):
            print(f"{index}. {pack_id}")
        print("0. Back")

        while True:
            choice = input("\nSelection: ").strip()
            if choice == "0":
                return None
            try:
                index = int(choice)
            except ValueError:
                index = 0
            if 1 <= index <= len(pack_ids):
                return pack_ids[index - 1]
            print("Invalid selection.")

    def _save_pack_decision(self, save):
        """Persist one optional tracking decision without blocking analysis."""
        try:
            save()
        except OSError as exc:
            self._print_save_error(exc)
            return False
        return True

    @staticmethod
    def _print_save_error(exc):
        print(f"Unable to save battery pack decision: {exc}")
        print("Continuing without Pack ID; persistent data was not changed.")

    def _select_flight(
        self,
        flight_log,
    ):

        if len(flight_log.flights) == 1:
            return flight_log.flights[0]

        print()
        print("Available Flights")
        print("=================")

        for index, flight_window in enumerate(
            flight_log.flights,
            start=1,
        ):
            print(
                f"{index}. "
                f"{format_time(flight_window.start_us)}"
                f" -> "
                f"{format_time(flight_window.end_us)}"
            )

        print("0. Cancel")

        while True:

            choice = input(
                "\nSelection: "
            ).strip()

            if choice == "0":
                return None

            try:
                index = int(choice)

                if (
                    1
                    <= index
                    <= len(flight_log.flights)
                ):
                    return flight_log.flights[
                        index - 1
                    ]

            except ValueError:
                pass

            print("Invalid selection.")

    def _select_instance(
        self,
        instances,
    ):

        if len(instances) == 1:
            return instances[0]

        print()
        print("Available Battery Instances")
        print("===========================")

        for index, instance in enumerate(
            instances,
            start=1,
        ):
            print(
                f"{index}. Battery {instance}"
            )

        print("0. Cancel")

        while True:

            choice = input(
                "\nSelection: "
            ).strip()

            if choice == "0":
                return None

            try:
                index = int(choice)

                if (
                    1
                    <= index
                    <= len(instances)
                ):
                    return instances[
                        index - 1
                    ]

            except ValueError:
                pass

            print("Invalid selection.")

    def _print_report(
        self,
        log_path,
        flight_window,
        analysis: BatteryAnalysis | None,
        pack_id=None,
    ):
        display_pack_id = pack_id if pack_id is not None else self.pack_id
        print(
            "\n"
            + format_battery_report(
                log_path,
                flight_window,
                analysis,
                display_pack_id,
            )
        )

    @staticmethod
    def _format_threshold(value):
        return _format_threshold(value)

    @staticmethod
    def _print_bounded_load_events(events):
        print("\n" + format_bounded_load_events(events))
