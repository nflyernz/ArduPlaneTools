# Battery Pack Management

Battery Pack Management maintains user-defined identities for physical battery packs and associates source BIN content with those identities. Select one BIN with the shared chooser, then open this tab to see whether its content identity is unseen, tracked to a Pack ID, or explicitly not tracked. An association applies to the entire source BIN, not to one flight within it.

The GUI can assign the selected BIN to an existing Pack ID, atomically create and assign a new Pack ID, or rename an existing Pack ID. Renaming is global: every BIN identity associated with the old Pack ID is updated. A log is identified by its SHA-256 content fingerprint, so identical-content files share an association even when their filenames differ.

Every write requires explicit confirmation. Opening the tab, selecting a BIN, refreshing its association or cancelling a confirmation does not change persistent data. Duplicate or invalid Pack IDs are rejected rather than merged, and failed writes retain the previously persisted store.

**Record AUTO takeoff history** is a separate explicit action available only for a tracked BIN. It processes all supported flights and battery instances through the existing history recorder and reports how many new observations were stored. Repeating the action for evidence already recorded reports zero; assignment and rename actions never record history automatically.

Pack identities and explicitly recorded history support Pack Performance reports. Historical observations retain their original ingest provenance, while current report ownership follows the source BIN's current association.

Pack assignment is user metadata. ArduPlaneTools cannot determine which physical battery was installed from DataFlash evidence alone, and it does not merge packs automatically.
