# APT Radio Link — Controlled RC-Failsafe Test Procedure

**Version:** 1.1 — purpose and receiver-behaviour clarification, 2026-10-12
**Purpose:** Observe **what ArduPlane detects and does** after controlled RC-input loss, using aircraft DataFlash BIN evidence and optional EdgeTX CSV telemetry.
**Companion document:** [`Radio_Link_Range_Walk_Comparison_Procedure.md`](Radio_Link_Range_Walk_Comparison_Procedure.md) — disarmed, landmark-marked RF comparison **without deliberate failsafe**.

> **Safety — propeller off for every stationary/ground test.** Remove the propeller, secure the aircraft and keep people clear of moving parts. Never rely on failsafe action to prevent motor operation. Arming, where needed to verify armed-state behaviour, must only be done under a safe prop-off setup.

## 1. Aim and evidence

This test deliberately removes the transmitter link to observe the aircraft's configured **short and long RC-failsafe behaviour, flight modes, timing and recovery**. The authoritative record of what ArduPlane detected and commanded is its **DataFlash BIN**. EdgeTX telemetry CSV, if available, is complementary transmitter-side RF evidence and must **not redefine** aircraft failsafe episodes.

This is **not** the RF range-walk comparison procedure. It is not a calibrated range-in-metres test or proof of physical motor operation. Use a separate power-cycle/test sequence and BIN for each controlled run.

## 2. Preparation

1. **Remove the propeller and secure the aircraft.** Verify the intended armed/disarmed state; prevent accidental throttle activation and do not rely on failsafe to keep the motor stopped.
2. Ensure aircraft DataFlash logging is enabled. If using an EdgeTX CSV, enable SD telemetry logging and set the radio date/time reasonably accurately. Perfect clock synchronization is not required.
3. Power-cycle transmitter and aircraft for a clean session. **After each aircraft power-cycle, wait for a valid GPS fix/date/time before deliberate link loss**, and check that GPS position has appeared on the transmitter if collecting CSV telemetry. This supports BIN↔CSV session pairing.
4. Record fixed ELRS transmitter power, packet rate, dynamic-power state and any other relevant RF settings. Keep them consistent during controlled comparisons.
5. Record ArduPlane `RC_FS_TIMEOUT`, `FS_LONG_TIMEOUT` and relevant receiver/throttle failsafe configuration. **Do not alter them just to satisfy an analyser.**
6. **Verify the receiver's output on RF loss.** A receiver that holds the last valid channels or emits unflagged preset values can conceal the physical RF loss from ArduPlane; others stop valid input or supply recognised failsafe signalling. Use a compatible receiver-specific failsafe mode (often *No Pulses* where available) and verify actual ArduPlane response during a prop-off transmitter-off test. Do not assume lost RF automatically creates an ArduPlane RC-input-loss episode.
7. For a deliberate **long-failsafe** test, plan a link-loss duration that clearly exceeds the applicable configured timing, with **at least five seconds of extra margin**. The exact starting point of the timers depends on the applicable firmware/input behaviour; do not assume a simplistic short-then-long sum.

## 3. Controlled bench transmitter-off test

1. Confirm **propeller removed** and aircraft secured.
2. Power-cycle the transmitter and aircraft if not already done for this run.
3. Wait for boot, fresh RC link, valid GPS fix/date/time and optional transmitter GPS telemetry.
4. **Arm with the propeller removed and the aircraft secured** when testing the armed-state failsafe actions. If deliberately conducting a disarmed test instead, record that limitation; the two outcomes are not equivalent.
5. Turn the transmitter **fully off**.
6. Keep it off for the applicable short/long failsafe timing **plus at least five seconds of margin** if testing the long action.
7. Turn transmitter back on; confirm RC-link recovery.
8. Select the desired safe flight mode if required after recovery; then disarm.
9. Power down and retain the **exact BIN** for this one session and optional corresponding EdgeTX CSV.

## 4. Controlled ground walk / deliberate link-loss test

This optional procedure is **different from the five-marker Range-Walk Comparison**. It intentionally approaches and passes the usable-link boundary to test aircraft failsafe behaviour.

1. Choose safe, accessible terrain, remove the propeller, secure the aircraft and prevent motor operation. Establish a fresh transmitter/aircraft session.
2. Wait for a good RC link, valid GPS/date-time and optional EdgeTX GPS telemetry.
3. Confirm and note the fixed ELRS TX power, packet rate and dynamic-power settings, plus failsafe parameters.
4. **Arm under prop-off, secured conditions** if testing armed-state actions; otherwise record that this is a disarmed-only test, not equivalent to an armed one.
5. Walk away with the transmitter until the RC link is clearly lost, without entering unsafe terrain. Avoid remaining near a fluctuating threshold if the purpose is to observe sustained long failsafe.
6. If testing the long response, remain beyond usable RC input long enough for configured timing **plus at least five seconds of margin**, subject to personal safety.
7. Walk back until control returns; verify mode and RC-link recovery, then disarm if armed.
8. Power down. Preserve this run's BIN and corresponding unedited EdgeTX CSV, if collected.

## 5. Interpreting evidence

- **BIN:** RC-input validity/loss episodes, short/long failsafe messages and actions, mode changes, recovery, armed state and parameter-aware timing assessments.
- **CSV:** Where supported by the radio protocol, RF telemetry and outages; these are **transmitter-side observations** and not equivalent to the flight controller's receiver-input state.
- **`RXLQ` may remain stale** during RC loss and is not independently proof of a working RC link.
- **Servo/throttle commands and PWM do not prove motor rotation.**
- No RF-loss distance is established unless transmitter-to-aircraft distance is independently measured.
- A timing judgement of **compatible** is not proof of millisecond-accurate event correspondence; interpret source firmware and observation resolution together.

## 6. Keep the two procedures separate

| Controlled RC-failsafe test (this document) | RF Range-Walk Comparison |
|---|---|
| Intentionally loses RC input | Measures comparative RF margin; does not seek failsafe |
| **BIN required** to establish ArduPlane behaviour | **EdgeTX CSV required**; BIN optional |
| May require safe prop-off arming to observe the armed response | **Disarmed** with propeller removed |
| No five-marker sequence required | **Five outward elevator markers** required |
| Tests short/long actions and recovery | Compares four outbound RF sections; return leg excluded |

Do not combine these as one experimental protocol, even if a given range walk incidentally encounters link loss.
