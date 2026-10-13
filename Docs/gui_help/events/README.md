# Event Timeline

Event Timeline presents a chronological view of selected events inside detected flight windows from an ArduPlane DataFlash BIN. Select one BIN in the GUI and choose **Analyse** to review every detected flight in order. The CLI workflow continues to let you select one flight when a BIN contains multiple flights.

The timeline currently merges firmware `MSG` records, landing-controller stage changes from `LAND`, and flight-mode records from `MODE`. Each line includes log-relative time, event type, and source detail. LAND telemetry is continuous, so only stage changes are emitted.

The timeline preserves source ordering after sorting by event time. An empty timeline means no supported event records were found within the selected flight window.

This is a focused event view rather than a reconstruction of every vehicle state. Absence of an event may reflect logging configuration or unavailable messages, and the timeline does not infer unlogged physical events.
