# Radio Link Test Procedure

Radio Link Analysis examines how ArduPlane detects and responds to RC-link loss through two separate tests:

1. **Bench transmitter-off/on:** Switch the transmitter fully off to trigger failsafe, then back on to observe recovery.
2. **Ground walk to link loss:** Walk away until RC control is lost, then return until control is restored.

Both tests require an aircraft DataFlash BIN. EdgeTX CSV telemetry is optional supporting evidence. Neither test is the five-marker Range-Walk Comparison procedure.

## Safety and preparation — both tests

1. Remove the propeller, secure the aircraft and keep people clear of moving parts.
2. Confirm DataFlash logging and normal receiver/transmitter operation.
3. Review configured short and long failsafe timeouts and actions. Do not alter them merely to satisfy the analyser.
4. Configure the receiver to provide an ArduPilot-recognised failsafe indication on RF loss. **No Pulses** is the recommended setting where supported; digital protocols may provide their own failsafe indication. Verify actual ArduPlane detection during the propeller-off test. Holding channels or sending unrecognised preset values may conceal RF loss.
5. Record TX power, packet rate, dynamic-power state and other relevant RF settings.
6. **Start fresh aircraft and transmitter power-on sessions for each test.** Wait for valid GPS/date-time before interrupting the link.
7. If recording EdgeTX telemetry, enable CSV logging and confirm GPS telemetry where available.
8. Arm only when deliberately testing armed-state actions, with the propeller removed and the aircraft secured. Disarmed results are not equivalent.

For deliberate long-failsafe tests, allow the applicable configured timeout plus **at least five seconds of additional margin**.

## Test 1 — Bench transmitter-off/on

This test observes ArduPlane's short and long failsafe actions and recovery during complete transmitter shutdown.

1. Establish normal RC control and the intended armed/disarmed state.
2. Switch the transmitter fully off.
3. Keep it off long enough to observe the intended failsafe response, including the additional margin for long failsafe.
4. Switch the transmitter back on.
5. Confirm RC-link recovery, check the resulting mode and select a safe mode if required.
6. Disarm if armed, then power down the aircraft.
7. Retain the BIN from that aircraft session.

EdgeTX CSV logging stops when the transmitter powers off. The recording after transmitter restart is a separate session. Do not combine the files or imply continuous telemetry during shutdown.

## Test 2 — Ground walk to link loss

This test observes failsafe behaviour as the usable RF link is lost and subsequently restored.

1. Choose a safe walking route; keep the aircraft stationary, secured and with propeller removed.
2. Begin fresh aircraft and transmitter recording sessions. Confirm normal RC control, GPS/date-time and RF settings.
3. Establish the intended armed/disarmed state under the precautions above.
4. Walk away while monitoring transmitter link and telemetry indications.
5. Continue until the RC link is clearly lost.
6. For long failsafe, remain beyond usable RC input for the configured timing plus the additional margin, provided it is safe to do so.
7. Walk back until RC control returns.
8. Verify control and mode recovery, then disarm if armed.
9. Power down and retain the aircraft BIN and corresponding EdgeTX CSV.

The transmitter normally remains powered and recording during this walk, unlike the transmitter-off test. The test does not establish physical RF-loss distance unless that distance is independently measured.

## Analyse the recordings

1. Open **Radio Link**, select the aircraft BIN and choose **Analyse**.
2. Review the summary and **Show detailed evidence**.
3. Use **Discover nearby** for optional CSV candidates.
4. Use **Auto pair** when a uniquely eligible CSV is available. Otherwise, use the diagnostic hints to guide **Use selected** or **Browse CSV…**.
5. Review pairing, alignment, RF measurements, missing telemetry and warnings.

Manual selection does not prove the BIN and CSV came from the same test.

## Interpreting results

- The BIN establishes logged failsafe episodes, commands, mode response and recovery.
- The CSV provides supplementary transmitter-side telemetry.
- Episode-specific RF measurements require adequate alignment evidence.
- Missing or zero-filled telemetry is not a valid RF measurement.
- Logged motor/throttle commands do not prove physical motor operation.
- The exact instant of physical RF loss cannot be inferred from sampled logging alone.
