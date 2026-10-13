# Radio Link Analysis

Radio Link Analysis identifies Plane RC-input failsafe episodes and aircraft response from an ArduPlane DataFlash BIN. Select a BIN and choose **Analyse** to open the summary. **Show detailed evidence** displays the full aircraft report from the same analysis result; switching views does not reread the BIN.

Aircraft BIN evidence remains authoritative for episode count and boundaries, armed state, short/long failsafe messages, mode response, recovery, configured timeouts, and commanded output evidence. The report can show sampled RC-input invalid spans, firmware action spans, timing compatibility, and incomplete log-boundary episodes.

After BIN analysis, **Discover nearby** lists EdgeTX CSV files beside the BIN and displays the same diagnostic hints used by the CLI. **Auto pair** accepts a candidate only when exactly one file satisfies the existing automatic-pairing rules. **Use selected** or **Browse CSV…** records an explicit user association; this does not prove that the files came from the same session. An unusable candidate does not prevent choosing another file.

Optional transmitter evidence appears below the unchanged aircraft report and identifies its CSV, pairing status, alignment status and warnings. **Remove overlay** removes that evidence without discarding the BIN result. Selecting another BIN invalidates the parsed aircraft context, candidate list and overlay.

Pairing and timeline alignment are separate evidence decisions. Coarse alignment may support qualified telemetry-availability context, but it is not a bounded clock uncertainty. Episode-specific numeric RF values require the existing bounded-alignment and sample-age evidence. Zero-filled or missing telemetry is not treated as a measured RF value, and partial CSV coverage remains labelled.

The analysis cannot measure the exact physical RF-loss instant, physical motor activity, transmitter distance, or a fresh RXLQ minimum from BIN alone. High or stale RXLQ never overrides asserted Plane failsafe evidence.
