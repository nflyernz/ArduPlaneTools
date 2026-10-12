# TAKEOFF glossary

- **TAKEOFF-mode execution** — A detector-owned Mode 13 interval; runtime AUTO `NAV_TAKEOFF` is tracked separately by entry context.
- **Firmware launch trigger** — The logged `Triggered AUTO` acceptance event.
- **Already-airborne entry** — Explicit firmware evidence that TAKEOFF began above or climbing toward takeoff altitude without a launch trigger.
- **Throttle suppression** — Firmware state that withholds takeoff throttle before release conditions are met.
- **TAKEOFF control completion** — Observed `STAT.Stage` transition from TAKEOFF to NORMAL, not a mode exit inferred as completion.
- **Censored by mode exit** — The execution ended before a completion observation.
- **AIRSPEED_MIN event** — First owned usable controller-airspeed observation meeting the effective configured minimum.
- **Commanded throttle / PWM** — Logged command evidence, not proof of motor activity or thrust.
- **RFNS** — Rangefinder distance evidence where supported.
