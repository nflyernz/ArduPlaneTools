# Range-Walk Comparison field-test procedure

This procedure records repeatable transmitter-side evidence for comparing receiver antenna arrangements. The GUI supports CSV and marker preview on Page 1, durable Walk 1 baseline creation on Page 2, and read-only saved history on Page 3. It does not yet process later walks or compare RF evidence.

## Safe ground preparation

1. Choose a clear walking route where the operator can remain safe and maintain control of the test setup.
2. Keep the aircraft on the ground and isolate propulsion so that no unexpected output can produce thrust. Removing the propeller is the preferred physical isolation where practical; follow the aircraft's electrical and battery safety procedures.
3. Do not arm the aircraft for this range walk.
4. Confirm the intended transmitter model, receiver installation and telemetry configuration before recording.

## Recording boundary and Walk 1 baseline

1. Begin with the transmitter powered down. Power it on using the intended model and start a fresh EdgeTX CSV-logging session for the test.
2. Keep the recording within that transmitter power-on session. End the session when the transmitter is safely powered down; a recording after restart is a separate session and must not be combined as continuous evidence.
3. Establish and record the Walk 1 **Baseline radio configuration**: the receiver, antennas, placement and orientation. Walk 1 is the baseline for every later antenna comparison.
4. Walk 1 simultaneously establishes the route and its marker recordings. A separate reconnaissance walk is not required.
5. Name five safe physical landmarks in fixed outward order. Landmark 5 is the safe turnaround; only the outward route to that point is measured.

## Record landmark markers

1. At each landmark, stop and hold the elevator stick deliberately at the calibrated full elevator-down position for the recommended three seconds.
2. Return the elevator stick to neutral after every hold before continuing toward the next landmark.
3. Preserve the original CSV, antenna arrangement, configured RF settings and field notes, including the landmark names and safe turnaround.
4. Detected holds are marker candidates. Confirm them against the field notes; do not manufacture a missing marker or map an uncertain candidate automatically.

For every later walk, retain the same five physical landmarks, the same landmark order, the same turnaround, the same walking route and the same RF settings. The receiver antenna arrangement is the variable being compared. Sections are bounded by physical landmarks and must not be assumed to have equal distance.

Missing or zero-filled telemetry is unavailable evidence, not measured poor signal. Do not infer range, failsafe behavior or an antenna winner from missing telemetry.

## Calibrate and preview in the GUI

1. Open **Range-Walk Comparison** and choose the original EdgeTX CSV. A shared aircraft BIN is not required.
2. `Ele` is the transmitter channel value recorded in the CSV. The GUI estimates neutral and endpoints only from sustained observations; an isolated minimum, maximum or brief movement is not a calibrated endpoint or marker.
3. Leave **Auto** selected to evaluate both higher and lower deflections. Auto prefers a direction only when its sequence of complete sustained holds and neutral returns is clearly stronger. It does not infer five markers from the field procedure.
4. Use **Inverse** to inspect the opposite direction. If Auto cannot establish a preferred direction, it reports the ambiguity, chooses deterministically and still gives Inverse a deterministic opposite.
5. The normal GUI workflow requires no manual neutral or near-down entry. Marker detection retains the existing 87.5% full-down threshold and minimum hold duration and uses a 33% neutral-return tolerance for the estimated neutral-to-endpoint span.
6. Choose **Detect markers** and review the direction used, evidence assessment, candidate count, onset, release and duration. Candidate detection does not confirm the five physical landmarks.
7. Choose **Next: Walk 1 Setup**. Record the **Baseline radio configuration**, describing the receiver, antennas, placement and orientation, and enter five physical landmark names. Use the required landmark 5 name for the safe turnaround; there is no separate turnaround-description entry.
8. With exactly five candidates, the GUI maps candidates 1–5 chronologically. If extra candidates exist, exclude them by selecting exactly five distinct candidates in increasing order without reordering them. If fewer than five exist, return to the field evidence rather than manufacturing a marker.
9. Expand **RF Settings** to record configured TX power, packet rate, RF mode/band and dynamic TX power where known. Unknown values are allowed but prevent later like-for-like comparison claims. Do not infer configured values from telemetry TPWR or RFMD.
10. Review the candidate onset, release and hold beside every named landmark, then choose **Save Walk 1**. The saved baseline retains the exact Page 1 marker evidence, uses landmark 5 as the turnaround and preserves a checksum-named copy of the original CSV. If the CSV contents changed after marker detection, saving is rejected and marker detection must be run again.

In the same Page 2 session, correct the saved label, Baseline radio configuration or optional RF settings with **Update saved Walk 1**. This retains the saved evidence, baseline identity, five landmark mappings and detection provenance. Changing the CSV or detection evidence ends that update association. Page 3 remains read-only and is not a general editor for older baselines.

Page 3, **History & Comparison**, reloads validated saved baselines after APT restarts. It is read-only and does not yet provide later-walk entry or RF comparison. Moving between pages preserves the current draft, while changing the CSV, Auto/Inverse direction or marker detection invalidates the accepted in-memory baseline based on the earlier evidence. RF section comparison, graphs and antenna comparison remain outside this GUI slice.
