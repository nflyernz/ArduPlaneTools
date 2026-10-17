# Radio Link Analysis

Radio Link Analysis identifies Plane RC-input failsafe episodes and aircraft response from an ArduPlane DataFlash BIN. Select a BIN and choose **Analyse** to open the summary. **Show detailed evidence** displays the full aircraft report from the same analysis result; switching views does not reread the BIN.

Aircraft BIN evidence remains authoritative for episode count and boundaries, armed state, short/long failsafe messages, mode response, recovery, configured timeouts, and commanded output evidence. The report can show sampled RC-input invalid spans, firmware action spans, timing compatibility, and incomplete log-boundary episodes.

After BIN analysis, **Discover nearby** lists EdgeTX CSV files beside the BIN and displays diagnostic hints for each candidate. **Auto pair** selects a CSV only when exactly one file meets the automatic pairing requirements. **When Auto pair is unavailable, use these hints to guide your selection**, then choose **Use selected** or **Browse CSV…** to select a CSV manually. Manual selection does not verify that the CSV belongs to the same flight. An unusable candidate does not prevent choosing another file.

Optional transmitter evidence appears below the unchanged aircraft report and identifies its CSV, pairing status, alignment status and warnings. **Remove CSV evidence** removes that evidence without discarding the BIN result. Selecting another BIN invalidates the parsed aircraft context, candidate list and overlay.

Pairing a CSV with a BIN does not necessarily mean their timestamps are accurately aligned. Approximate alignment may help indicate whether transmitter telemetry was available around a failsafe event, but is not precise enough to report event-specific RF values. Those measurements are reported only when timing accuracy and sample age meet the required checks. Missing readings or zero-filled telemetry are not treated as valid RF measurements, and incomplete CSV coverage is identified.

The analysis cannot measure the exact physical RF-loss instant, physical motor activity, transmitter distance, or a fresh RXLQ minimum from BIN alone. High or stale RXLQ never overrides asserted Plane failsafe evidence.
