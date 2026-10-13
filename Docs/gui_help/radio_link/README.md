# Radio Link Analysis

Radio Link Analysis identifies Plane RC-input failsafe episodes and aircraft response from an ArduPlane DataFlash BIN. Select a BIN and choose **Analyse** to open the summary. **Show detailed evidence** displays the full aircraft report from the same analysis result; switching views does not reread the BIN.

Aircraft BIN evidence remains authoritative for episode count and boundaries, armed state, short/long failsafe messages, mode response, recovery, configured timeouts, and commanded output evidence. The report can show sampled RC-input invalid spans, firmware action spans, timing compatibility, and incomplete log-boundary episodes.

The GUI currently provides aircraft BIN evidence only. Optional transmitter CSV evidence remains available through the CLI, where it is labelled separately and subject to the existing pairing and alignment requirements. Zero-filled or missing telemetry is not treated as a measured RF value.

The analysis cannot measure the exact physical RF-loss instant, physical motor activity, transmitter distance, or a fresh RXLQ minimum from BIN alone. High or stale RXLQ never overrides asserted Plane failsafe evidence.
