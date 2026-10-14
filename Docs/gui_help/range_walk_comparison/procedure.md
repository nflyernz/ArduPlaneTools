# Range-Walk Comparison field-test procedure

This procedure records repeatable transmitter-side evidence for comparing receiver antenna arrangements. The current GUI supports CSV and marker-candidate preview only; it does not yet confirm a baseline or compare multiple walks.

## Safe ground preparation

1. Choose a clear walking route where the operator can remain safe and maintain control of the test setup.
2. Keep the aircraft on the ground and isolate propulsion so that no unexpected output can produce thrust. Removing the propeller is the preferred physical isolation where practical; follow the aircraft's electrical and battery safety procedures.
3. Do not arm the aircraft for this range walk.
4. Confirm the intended transmitter model, receiver installation and telemetry configuration before recording.

## Recording boundary and Walk 1 baseline

1. Begin with the transmitter powered down. Power it on using the intended model and start a fresh EdgeTX CSV-logging session for the test.
2. Keep the recording within that transmitter power-on session. End the session when the transmitter is safely powered down; a recording after restart is a separate session and must not be combined as continuous evidence.
3. Use the original receiver antenna installation for Walk 1. Walk 1 is the baseline for every later antenna comparison.
4. Walk 1 simultaneously establishes the route and its marker recordings. A separate reconnaissance walk is not required.
5. Name five safe physical landmarks in fixed outward order. Landmark 5 is the safe turnaround; only the outward route to that point is measured.

## Record landmark markers

1. At each landmark, stop and hold the elevator stick deliberately at the calibrated full elevator-down position for the recommended three seconds.
2. Return the elevator stick to neutral after every hold before continuing toward the next landmark.
3. Preserve the original CSV, antenna arrangement, configured RF settings and field notes, including the landmark names and safe turnaround.
4. Detected holds are marker candidates. Confirm them against the field notes; do not manufacture a missing marker or map an uncertain candidate automatically.

For later walks, repeat the same five landmarks in the same order, use the same turnaround and retain the same RF settings where possible. Sections are bounded by physical landmarks and must not be assumed to have equal distance.

Missing or zero-filled telemetry is unavailable evidence, not measured poor signal. Do not infer range, failsafe behavior or an antenna winner from missing telemetry.

## Calibrate and preview in the GUI

1. Open **Range-Walk Comparison** and choose the original EdgeTX CSV. A shared aircraft BIN is not required.
2. `Ele` is the transmitter channel value recorded in the CSV. The GUI may suggest neutral and endpoint values from sustained observations; an isolated minimum or maximum is not used as a calibrated endpoint.
3. Select whether the deliberate full elevator-down holds use the higher or lower `Ele` value. Values are model-specific and may be positive or negative. The software does not infer control direction from the sign or extrema.
4. Check the proposed neutral and full-down values against the recorded test, then explicitly confirm the calibration. Suggestions are evidence clues, not verified control direction.
5. If a reliable suggestion is unavailable, open **Advanced / Manual calibration** and enter the operator-confirmed full-down and neutral values. The optional near-down threshold may remain blank to use 87.5% of the calibrated neutral-to-down span.
6. Choose **Detect markers** and review every candidate's onset, release and duration. Candidate detection does not confirm the five physical landmarks.

The current GUI stops at CSV and marker preview. Baseline acceptance, five-landmark mapping, later walks, RF section comparison, graphs and antenna comparison remain in the established CLI workflow.
