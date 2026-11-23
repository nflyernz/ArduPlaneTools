# Battery Pack History v2 — Stage 2A protection

Stage 2A uses `battery_pack_history_v2.json` beside the existing application-data
`battery_pack_history.json`. Management accepts explicit paths for all three stores
in tests. The v2 file is read only during inspection and is never created just to
show Pack IDs. Missing means empty; malformed, unsupported and unreadable means
management is blocked.
Store paths must be distinct and may not be symbolic links; a broken v2 link
cannot masquerade as an absent store.

The Pack-store deletion, planning and unused-ID APIs promote a legacy v1 caller
to a coordinated context when the sibling v2 file exists, or when application-data
paths are used. They also promote a direct v2 caller when a sibling v1 file exists
or application-data paths are used. Isolated explicit-path tests without a sibling
history retain their legacy behavior. Callers using nonstandard paths for both
stores must supply `CoordinatedHistory` explicitly; a single store cannot discover
an arbitrarily named second file. A pending journal always forces coordinated
recovery, including when v2 was initially absent.

The deletion plan names v1 and v2 observation IDs separately, plus BIN SHA-256
associations, retained ownership updates and SHA-256 revisions of all three
stores. Ownership continues to use ingest Pack ID, retained owners and rename
aliases. No v1/v2 event equivalence is assumed. The plan is recomputed before
deletion and a changed file or confirmation is rejected. Unused Pack ID eligibility
includes both histories. Rename, archive and restore do not rewrite provenance.

## Durable deletion

Before replacing any store, deletion creates a directory beside the Pack metadata
file. It contains fsynced backups of every initially present store and a checksummed
manifest with exact paths, revisions and `prepared` state. The journal directory is fsynced
before the first store write. The three stores are then replaced individually.
Their parent directories are fsynced. Only after all writes succeed is the
manifest changed to `committed` and fsynced. The journal directory is atomically
renamed to a nonblocking completed name before its files are removed. Interrupted
completed-journal cleanup cannot be mistaken for an active transaction.

An ordinary write failure restores all three files, including initially absent
files, and reloads all three in-memory stores. If restore or reload fails, the
journal remains and management reports a recovery error. At the next management
entry, a `prepared` journal restores the original files before loading Pack IDs.
A `committed` journal means all writes completed and only cleanup remains. A
missing manifest in an *active* journal, invalid manifest or damaged backup blocks
management; it is not interpreted as empty history. If a fault happens while the
committed marker is being written or synced and the marker is visible, deletion
raises an explicit uncertain-outcome error, retains the journal, and requires a
refresh before retry. Faults during postcommit cleanup do not report deletion as
rolled back. Original BIN files are never part of the transaction.

The journal provides deterministic recovery from a process interruption after
the prepared manifest is durable. It does not make three JSON replacements one
filesystem-atomic operation. A crash while creating the journal can leave an
incomplete journal that blocks management and needs manual investigation, while
no stores have yet been mutated. Filesystem or hardware failure that violates
`fsync`/atomic-rename guarantees can require manual recovery. Concurrent writers
that ignore the journal are outside this transaction protocol; management checks
loaded and confirmed revisions but cannot lock unrelated processes.

On Windows, Python cannot open a directory with `os.open`, and Windows does not
document `FlushFileBuffers` for directory handles. File and journal contents are
still flushed, and ordinary write failures and process interruptions recover
through the journal. Windows directory-entry persistence across sudden power loss
is **not guaranteed**: a rename or journal creation may be lost even after file
contents were flushed. A resulting incomplete active journal blocks management
for manual investigation. The directory fsync behavior above applies to macOS
and Linux only.

Stage 2A does not record v2 observations, migrate history or change measurement
or reporting semantics. Production pack deletion must continue to coordinate
both stores before v2 ingestion can be enabled.
