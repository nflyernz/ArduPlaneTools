# Battery Pack Performance v2: Stage 1 schema

This stage defines and tests an isolated `battery-load-v2` observation format.
No production recorder, GUI, application-data file, or `battery-load-v1`
serializer changes. The v2 store requires an explicit path, so it cannot
silently create a live history file.

## Storage decision

The existing history file has a strict version-1 envelope and AUTO-only
observation contract. Adding pilot records there would make older readers
reject the file, and changing `SUPPORTED_ANALYSIS_SEMANTICS` would cause the
existing newest-observation logic to treat v1 and v2 keys as if they always
identified the same physical event. They do not: v1 identity includes the
bounded AUTO event interval, whereas v2 uses the logged takeoff timestamp.
Stage 1 therefore uses a separate version-2 envelope and store. V1 files and
IDs remain byte-for-byte unaffected.

This isolation has an ownership cost. `BatteryPackStore` can resolve v2
`pack_id_at_ingest`, `source_sha256`, and `observation_id` when an explicit v2
store is passed to its rename, archive, deletion-plan, or deletion methods.
The current production management flow passes only the v1 store. Before v2
ingestion, deletion must plan **both** histories together and commit their
updates atomically; otherwise a v2 observation could be orphaned. Stage 1
does not wire a v2 store into that flow or expose a live v2 path.

## Identity and provenance

`physical_event_id` is a SHA-256 of a canonical array containing a namespace,
source BIN SHA-256, battery instance, FlightWindow start/end, and logged
takeoff timestamp. T0, T1, plateau bounds and classification are excluded.
`observation_id` hashes the physical ID with `battery-load-v2`. Changing
measurements for one observation ID is a conflict, not another event. This
scheme does not equate any v1 AUTO key with a v2 key; a future migration needs
an explicit, reviewed matching procedure. The FlightWindow start/end are part
of this key, so a segmentation change also changes identity; cross-segmentation
reconciliation is deferred to that reviewed policy.

Each record retains original pack ownership, source filename, flight number,
takeoff type and mode (`AUTO`, `MANUAL`, `FBWA`), plus optional complete
GPS-to-UTC provenance. UTC is checked against its GPS anchor and logged
takeoff timestamp. Physical contact is explicitly marked as inferred.

## Evidence and validation

Nested load evidence retains qualified T0, current reference and threshold,
T1, raw peak current, minimum loaded voltage with concurrent current, strict
low-current voltage drop with baseline, recovery, statuses, and limitations.
A pilot observation may have a qualified T0 while strict voltage drop remains
unavailable. Raw extrema may remain available when a qualification fails.

Nested plateau evidence retains both observed intervals, paired median
voltage/current values, voltage and current differences, status and a specific
limitation when unavailable or partial. It cannot populate a numerical
plateau change without a fully qualified pair. Plateau change never fills the
strict voltage-drop field. Finite values, exact schema fields, nonnegative
times, ordered intervals, FlightWindow/T0/T1 bounds, canonical identities,
and consistent statuses are checked before serialization or storage.
The schema also requires both qualified plateau intervals to span at least
0.8 s, the pre-onset end to fall within the approved 501 ms T0 recency bound,
the loaded end to fall within T0 + 6 s, and loaded median current to reach
both pre-onset + 5 A and 70% of the qualified launch reference. Raw-sample
continuity remains an evaluator responsibility, since medians cannot prove it.
Qualified recovery requires a qualified T1 and a later recovery timestamp.
For MANUAL and FBWA, qualified T0 must fall within the pilot detector's
inclusive logged-takeoff −8 s to +4 s search window. This pilot-specific
bound is not imposed on AUTO. Qualified plateau medians require positive
voltages and nonnegative currents; arithmetic consistency alone is
insufficient to validate physical measurements.

JSON uses sorted observation IDs and keys, rejects NaN, and is written by
temporary-file replacement. Duplicate identical records are idempotent;
conflicting evidence rejects the whole batch. Invalid persisted content
raises an error before any mutation. No missing telemetry is synthesized.
Replaying the same analytical evidence after a source filename or Pack ID
change is idempotent; only these two mutable provenance fields are ignored
for equality, and the original stored owner and filename remain intact.

## Limits and next decision

Neither strict voltage drop nor observed plateau change alone estimates
battery internal resistance or state of health. Telemetry cannot prove
physical touchdown. Missing and unsupported measurements remain nullable with
explicit status/limitations. Before any ingestion stage, review cross-store
pack deletion, backup/rollback, mixed-version presentation, and a deliberate
v1/v2 event-equivalence policy. No migration is part of Stage 1.
