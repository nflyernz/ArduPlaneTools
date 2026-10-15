# Range-Walk glossary

- **Walk 1 baseline** — The fixed original-antenna walk used for every comparison.
- **Baseline radio configuration** — The operator's description of the Walk 1 receiver, antennas, placement and orientation. It is editable metadata; the stored version-1 field remains `antenna` for compatibility.
- **Landmark** — One user-named physical position assigned to a detected candidate in chronological order.
- **Turnaround** — The required name for landmark 5, where the outward measured route ends safely; it has no separate description field.
- **Extra candidate** — A detected hold excluded from the five chronological landmark assignments, never moved out of recorded order.
- **RF Settings** — Optional operator-entered TX power, packet rate, RF mode/band and dynamic-power state retained for later comparability checks.
- **Managed CSV** — The checksum-named preserved copy of the original transmitter recording owned by a saved baseline.
- **Update saved Walk 1** — Corrects the saved label, Baseline radio configuration or optional RF settings while retaining the original evidence identity and landmark mapping.
- **History & Comparison** — The read-only GUI page for validated saved baselines; later walks and comparisons are not yet available there.
- **Moving section** — Release of marker N to onset of marker N+1; five landmarks define four sections.
- **Marker hold** — Stationary interval retained as separate landmark evidence.
- **1RSS** — Receiver-reported primary RSSI in dBm returned through telemetry.
- **RQly** — Receiver-reported uplink receive quality percentage.
- **RSNR** — Receiver-reported signal-to-noise ratio.
- **P10** — Lower-tail 10th percentile of eligible logged values.
- **Observed-time coverage** — Portion of section time represented by usable observations; it is not RF refresh freshness.
- **Unavailable telemetry** — Missing/placeholder RF evidence excluded from numeric statistics.
