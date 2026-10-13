# Radio Link glossary

- **RCI2** — Aircraft-side sampled RC-input validity evidence used for episode boundaries.
- **Short / long failsafe** — Plane firmware failsafe stages and actions; both timers originate from the last acceptable RC input.
- **Sampled invalid span** — Time between logged invalid and revalidated RCI2 observations, not the exact RF-loss duration.
- **Action span** — Time between logged failsafe assertion and clear messages where both exist.
- **RXLQ** — Aircraft-logged receiver link quality; it may remain stale during complete loss.
- **RQly / 1RSS / RSNR** — Receiver-reported uplink metrics carried in EdgeTX telemetry.
- **Telemetry unavailable** — No usable transmitter-side RF observation; it is not a measured zero.
- **Pairing** — Evidence that a BIN and CSV belong to the same session.
- **Alignment** — Estimated relationship between aircraft and transmitter timelines.
- **Commanded output** — Logged PWM or command evidence, not physical motor activity.
- **Summary view** — Compact aircraft-BIN results produced by the existing Radio Link summary formatter.
- **Detailed evidence** — The full aircraft-BIN report from the same cached detector result.
