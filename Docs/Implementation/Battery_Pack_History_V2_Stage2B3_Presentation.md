# Battery Pack History v2 — Stage 2B3 presentation

Pack Performance retains its existing heading, Pack ID selection and byte-for-
byte v1 report when no owned v2 observation exists. V1 still has **FIRST TAKEOFF
BY BATTERY SESSION** and **ALL AUTO TAKEOFFS** with unchanged calculations. A
separate **V2 — TAKEOFF LOAD EVIDENCE** section displays owned AUTO, MANUAL and
FBWA analytical observations. V1 and v2 AUTO entries are shown separately and
are never summed as physical takeoffs or matched by guessed timestamp.

The v2 section labels qualified, partial and unavailable onset, current
reference, T1, strict low-current voltage drop, recovery and sustained-load
voltage evidence. Raw extrema are explicitly observed values. Five-second
follow-up does not qualify low-load recovery. **Observed voltage under sustained
load** describes medians over two qualifying periods, not maximum sag, battery
internal resistance or state of health. For example, pre-load 16.00 V at
5.00 A and loaded 14.50 V at 21.00 A yields an observed difference of 1.50 V
and 16.00 A. A separate qualified low-current voltage drop may be 2.00 V; the
two measurements are not interchangeable. Missing UTC stays unavailable, and
AUTO logged transition time does not prove physical ground contact.

Pack ownership is resolved from each stored observation through
`BatteryPackStore.history_owner_for`, honoring renames and retained owners even
when a BIN is reassigned. V2 records sort by available UTC, source fingerprint,
flight number, BAT instance, logged transition time and stable IDs. The GUI and
terminal use one formatter. Neither requires the original BIN to view saved
history. A missing v2 file is normal and viewing never creates it.

Both history versions are validated before reporting. A malformed or
unsupported file stops the report. A pending Stage 2A deletion journal also
stops reporting: recovery belongs to Pack Management because it can write the
Pack Store and history files, while Pack Performance remains read-only. Mixed
history editing, recording and cross-version health metrics are outside this
stage.
