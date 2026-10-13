# Battery Pack Management glossary

- **Pack ID** — User-provided name for one physical battery pack.
- **Log fingerprint** — SHA-256 content identity used to associate a BIN with a pack.
- **Tracked** — The log fingerprint is associated with a Pack ID.
- **Not tracked** — The log was explicitly retained without a Pack ID association.
- **Unseen** — No pack decision has been stored for that log fingerprint.
- **Rename** — Change a Pack ID while preserving its owned associations.
- **Assignment** — The stored relationship between a log fingerprint and a Pack ID.
- **Persistent store** — Local data holding Pack IDs and assignments; it is separate from the BIN.
- **History recording** — Explicit whole-BIN ingestion of supported AUTO takeoff evidence for the currently tracked Pack ID.
- **Idempotent recording** — Repeating history ingestion does not add a duplicate observation for the same logged event and analysis semantics.
