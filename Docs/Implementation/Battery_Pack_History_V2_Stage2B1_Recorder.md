# Battery Pack History v2 — Stage 2B1 recorder

The standalone `BatteryPackHistoryV2Recorder` requires a decoded `FlightLog`, an
original BIN path whose contents match the supplied SHA-256, the ingest Pack ID,
configuration and an explicit `BatteryPackHistoryV2Store`. Nothing in ordinary
Battery Analysis, terminal Pack Management or GUI ingestion calls this recorder.
It discovers and validates every candidate before one idempotent store batch.

For AUTO, the recorder reuses the independently supported AUTO bounded event
and Battery Load Response. The physical-event timestamp is the FlightWindow
start **only when that timestamp occurs in the source GPS rows**. The existing
FlightWindow detector selects its start from a recorded GPS speed transition;
an AUTO candidate without that row is excluded. This timestamp is distinct from
BAT T0 and the earlier `Triggered AUTO` message. It is telemetry evidence for
ground-to-flight transition, not physical-contact proof.

For MANUAL and FBWA, it reuses the pilot detector's logged GPS transition and
per-instance `PilotTakeoffMeasurement`. Rejected detector candidates never enter
the recorder. Identity uses the existing v2 physical-event and observation-ID
functions, with no attempt to equate v1 AUTO keys. The v2 store retains first
ingest Pack ID and filename on replay.

The load record preserves independent T0, high-current reference, T1 and strict
low-current voltage drop qualifications. T1 confirms current below 80% of the
reference for three seconds. The evaluator's five-second follow-up is an
observed voltage/current sample that may still be under propulsion load; its
values appear in the limitations text, while v2 recovery remains unavailable
with null recovery fields. No separate low-load recovery qualification or T2
exists at this stage. Raw peak and minimum measurements may remain when
qualification is partial. A missing baseline never becomes a qualified drop.
Pilot observed plateaus use only the established plateau evaluator; AUTO
plateau status is unavailable. Plateau change never fills the strict
voltage-drop field. Neither value alone establishes internal resistance or
battery state of health.

GPS UTC provenance uses only the existing causal `gps_time_at` evidence. If the
available GPS records cannot establish UTC, all optional UTC/anchor fields stay
null. When a GPS-anchored BAT observation supplies raw extrema without T0, its
original quality status is retained in load limitations, including complete
sampling or gaps, invalid timestamps and missing paired voltage/current values.
Those raw values never qualify onset or strict voltage drop. Missing or invalid
BAT evidence stays explicit. The v2 schema remains the
final qualification gate; an invalid candidate or conflicting analytical replay
rejects the entire batch without changing an existing store.
The recorder reloads the explicit v2 store immediately before the batch write,
so a file corrupted after the store object was constructed is not overwritten.
