# Battery Pack Management

Battery Pack Management maintains user-defined identities for physical battery packs and associates source BIN content with those identities. This GUI tab is not yet connected; management is available through the CLI.

The workflow can rename a known Pack ID or change the pack assignment for a selected log. A log is identified by its content fingerprint, so assignment is based on file contents rather than only its filename. Users may select an existing pack, create a new Pack ID, or mark analysis as not tracked where the surrounding workflow offers that choice.

Pack identities support Battery Analysis history and Pack Performance reports. The store reports errors without intentionally replacing persistent data when an operation fails.

Pack assignment is user metadata. ArduPlaneTools cannot determine which physical battery was installed from DataFlash evidence alone, and it does not merge packs automatically.
