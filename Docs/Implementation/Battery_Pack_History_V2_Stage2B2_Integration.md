# Battery Pack History v2 — Stage 2B2 integration

Battery Pack Management now offers a separate, explicitly confirmed **Record v2
takeoff history** action for a selected tracked BIN. The existing AUTO/v1
action and ordinary Battery Analysis remain unchanged. The action uses the
existing GUI worker to decode the BIN, and the Stage 2B1 recorder to discover
and validate AUTO, MANUAL and FBWA observations. No v2 file is created by
lookup, cancelled confirmation or failed preflight.

The service checks the selected BIN hash, Pack Store revision and association,
and validates coordinated v1/v2 history before decoding. Immediately before
the recorder's single v2 batch write, it repeats those checks and compares
both history-file revisions with their pre-decode values. The recorder also
reloads v2 storage and rejects conflicting analytical evidence for an existing
observation ID. A replay retains the original Pack ID and source filename;
current assignment does not reassign old observations. Zero additions means
either no eligible candidate or an idempotent replay.
This final validation path also runs for a decoded BIN with no FlightWindows or
no eligible takeoff candidates. An empty batch does not create a v2 file.

The recording action's only successful persistent write is the v2 store's
atomic file replacement. Its coordinated-history preflight may first perform
Stage 2A deletion-journal recovery, which can restore the Pack Store and both
history files before recording is considered; a changed revision then rejects
the stale selection. Apart from that recovery, the action does not write Pack
Store metadata or v1 history. A rejected batch
does not write a partial set. A storage failure before replacement leaves the
old v2 file intact; this single-file operation does not use the Stage 2A
coordinated-deletion journal. The checks do not provide cross-process locking:
a concurrent writer between final revision check and replacement can still
race, and a failure after replacement may leave the new v2 file despite an
error returned to the caller. Windows uses the existing v2 store's file
replacement behavior; the Stage 2A journal's directory durability guarantees
do not extend to this write.

V1 and v2 remain separate because their observation schemas and physical-event
identities differ. The v1 Pack Performance table is unchanged. Mixed-history
presentation and comparison are deferred to Stage 2B3. Five-second follow-up
does not qualify low-load recovery, and AUTO liftoff remains inferred from
logged telemetry rather than proven physical contact.
