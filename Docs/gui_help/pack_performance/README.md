# Pack Performance

Pack Performance compares stored battery observations owned by one physical Pack ID. It uses local pack assignments and history previously recorded by supported Battery Analysis workflows. It does not require a selected BIN.

Open the tab to reload known physical Pack IDs and stored history. Choose a Pack ID and select **View report**. Use **Refresh** after Pack Management changes; the current selection is retained when that Pack ID still exists.

The report identifies the selected Pack ID and presents two views: the first retained AUTO takeoff in each battery session, and all retained AUTO takeoff observations. Rows include date, source log, flight number, capacity used before the event, average and peak current, pre-load and minimum loaded voltage, voltage sag, and voltage recovery when available.

Only observations whose source fingerprint is currently assigned to the selected Pack ID are included. Reassigning a log changes ownership in the report without rewriting the original BIN.

This tab is read-only. It does not create, rename, reassign or remove Pack IDs, and it does not record observations. Use Battery Pack Management for those explicit operations.

This is descriptive history, not a battery-health score, capacity test, remaining-life prediction, or guarantee that different flights imposed comparable loads.
