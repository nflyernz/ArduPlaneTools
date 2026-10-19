# Range-Walk Comparison Test Procedure

This test compares radio configurations using repeated walks along the same route. Walk 1 establishes the baseline for every subsequent comparison.

## Before the walk

1. Choose a safe walking route with five identifiable landmarks. Landmark 5 is the turnaround point.
2. Keep the aircraft stationary and disarmed, with the propeller removed.
3. Confirm the transmitter model, receiver, antennas and telemetry are working correctly.
4. Record the transmitter power, packet rate, RF mode and dynamic-power setting.
5. Start a fresh EdgeTX CSV recording. Keep each walk within one transmitter power-on session.

## Walk 1 — Establish the baseline

1. Start at the aircraft and walk towards the first landmark.
2. At each landmark, stop and hold full elevator-down for approximately **three seconds**.
3. Return the elevator stick to neutral before continuing to the next landmark.
4. Repeat at all five landmarks, keeping them in the same outward order.
5. Landmark 5 marks the end of the measured route. Turn around and return to the aircraft.
6. Stop recording and preserve the original CSV, landmark names, radio configuration and RF settings.

Five landmarks define four measured sections. Only the outward route is used for comparison; the return walk is excluded.

## Save Walk 1 in APT

1. Open **Range-Walk Comparison** and choose the recorded EdgeTX CSV. No aircraft BIN is needed.
2. APT examines the elevator-stick movements recorded during the walk to identify the landmark markers. Leave **Automatic (recommended)** selected, then click **Detect markers** to evaluate the recorded movements in both directions.
3. Review the detected marker candidates. If necessary, select **Opposite direction** and click **Detect markers** again to evaluate the movements in the other direction.
4. Choose **Next: Walk Setup**.
5. Enter the **Baseline radio configuration**, describing the transmitter, receiver, antennas, placement and orientation.
6. Name the five landmarks, with landmark 5 identifying the turnaround.
7. Check that the detected markers correspond to the physical landmarks in chronological order. Exclude extra candidates rather than changing their recorded order.
8. Enter the configured **RF Settings**, where known.
9. Select **Save Walk 1**.

A complete Walk 1 baseline requires five confirmed marker candidates. If a marker was not recorded, repeat the walk rather than inventing one.

You can correct the saved label, radio configuration or RF settings during the same setup session using **Update saved Walk 1**.

## Record an additional walk

1. Repeat the same walking route, five landmarks, marker holds and turnaround.
2. Keep the transmitter RF settings unchanged. Change only the radio configuration you intend to compare, and record what changed.
3. Save a new EdgeTX CSV.
4. In APT, choose that CSV and detect the markers.
5. Open **Next: Walk Setup** and select **Record an additional walk against a saved baseline**.
6. Choose the correct Walk 1 baseline and enter the **Test radio configuration**.
7. Match each detected marker to its actual physical landmark. Leave missing markers unassigned; do not assume that four detected markers represent landmarks 1–4.
8. Save the additional walk.

An additional walk can be saved with missing marker evidence, but the field procedure still requires visiting all five landmarks.

## Review saved walks

Open **History & Comparison** to view saved baselines and their additional walks.

APT shows which landmarks were confirmed or missing and which sections have enough marker evidence for comparison. Both ends of a section must be identified.

Select the saved Walk 1 baseline and one associated walk, then choose **Compare selected walks**. Review all four section rows, coverage qualifications, plots and detailed metadata. Settings inherited from Walk 1 are not independent confirmation of the later walk's configuration.

**Important:** Missing or zero-filled RF telemetry is not a measurement of poor signal. The comparison does not establish an exact range limit or prove which radio configuration will perform best in flight.
