# Pack Performance

Pack Performance compares stored battery observations owned by one physical Pack ID. It uses local pack assignments and history previously recorded by supported Battery Analysis workflows. This GUI tab is not yet connected; use the CLI report.

The report identifies the selected Pack ID and presents two views: the first retained AUTO takeoff in each battery session, and all retained AUTO takeoff observations. Rows include date, source log, flight number, capacity used before the event, average and peak current, pre-load and minimum loaded voltage, voltage sag, and voltage recovery when available.

Only observations whose source fingerprint is currently assigned to the selected Pack ID are included. Reassigning a log changes ownership in the report without rewriting the original BIN.

This is descriptive history, not a battery-health score, capacity test, remaining-life prediction, or guarantee that different flights imposed comparable loads.
