# Radio Link Analysis

Radio Link Analysis identifies Plane RC-input failsafe episodes and aircraft response from an ArduPlane DataFlash BIN. The GUI tab is not yet connected; use the CLI workflow. Optional EdgeTX CSV evidence may enrich a BIN-defined session when conservative pairing and alignment requirements are met.

Aircraft BIN evidence remains authoritative for episode count and boundaries, armed state, short/long failsafe messages, mode response, recovery, configured timeouts, and commanded output evidence. The report can show sampled RC-input invalid spans, firmware action spans, timing compatibility, and incomplete log-boundary episodes.

Optional transmitter CSV evidence is labelled separately. It can describe session RF observations, telemetry gaps, and episode context only at the alignment strength supported by the data. Zero-filled or missing telemetry is not treated as a measured RF value.

The analysis cannot measure the exact physical RF-loss instant, physical motor activity, transmitter distance, or a fresh RXLQ minimum from BIN alone. High or stale RXLQ never overrides asserted Plane failsafe evidence.
