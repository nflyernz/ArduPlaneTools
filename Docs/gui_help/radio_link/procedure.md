# Radio Link ground-test procedure

This procedure gathers controlled aircraft-side RC-failsafe evidence for Radio Link Analysis. It is a ground test. Adapt the preparation to the aircraft, site, firmware configuration and operator responsibilities.

## Safe preparation

1. Secure the aircraft in a clear test area and keep people away from control surfaces and propulsion.
2. Isolate propulsion so that an unexpected output cannot produce thrust. Removing the propeller is the preferred physical isolation where practical; follow the aircraft's electrical and battery safety procedures.
3. Confirm that the flight controller, receiver and transmitter installation are complete and powered as intended for the test.
4. Verify the configured Plane RC-failsafe settings, including the short and long timeout and action settings applicable to the installed firmware. Record any settings needed to interpret the test.
5. Establish a valid RC link and confirm normal control input before interrupting it.
6. If the intended evidence requires an armed state, arm only after propulsion is physically isolated and all ground-test precautions are in place. Radio Link Analysis preserves armed, disarmed and unknown states separately.

## Recording boundaries

Keep the aircraft and transmitter recordings within their own power-on sessions. Do not combine recordings across power cycles or treat separate sessions as continuous evidence.

- **Aircraft BIN session:** Begin with the aircraft powered down, then use a fresh flight-controller power-on session for the intended test. After restoring valid RC input, confirming the expected recovery and disarming where applicable, power down the aircraft safely to end that session. Retain the BIN produced by that single aircraft session.
- **EdgeTX CSV session:** Begin with the transmitter powered down, then use a fresh transmitter power-on and CSV-logging session with the intended model and telemetry configuration. Keep the corresponding recording within that transmitter session and end it when the transmitter is safely powered down.

If switching off the transmitter is part of the failsafe test, EdgeTX CSV logging stops at shutdown. A recording made after restarting the transmitter belongs to a separate transmitter session; there is no continuous transmitter telemetry across the power-off interval. Keep the separate CSV files separate.

Aircraft and transmitter power-cycle boundaries describe their respective recording sessions. Matching or similar boundaries alone do not prove that a BIN and CSV belong to the same test; pairing and alignment still require the evidence review described below.

## Controlled interruption

1. Within the fresh aircraft session, allow the aircraft to establish normal RC input before beginning the intended test.
2. Deliberately interrupt RC input using the planned test method.
3. Observe the configured short-failsafe response and, if the test plan calls for it, maintain the interruption long enough to observe the configured long-failsafe response.
4. Record observable mode changes or messages without relying on them as the only evidence. The BIN analysis associates logged RCI2, MSG and MODE evidence according to their separate meanings.
5. Restore valid RC input deliberately and confirm that control input and the expected flight mode have recovered before ending the recording.
6. Disarm where applicable, power down the aircraft safely to end the session and retain its BIN.

Transmitter shutdown is one controlled way to interrupt RC input. It does not exercise every interference, antenna, receiver, protocol or partial-link failure mode and must not be treated as a complete RF-system qualification.

## Analyse the BIN

1. Open **Radio Link** in ArduPlaneTools and select the recorded BIN.
2. Choose **Analyse** and review the summary first.
3. Open **Show detailed evidence** to inspect sampled RC-input invalid boundaries, short and long failsafe messages, mode response, recovery, timing qualifications and commanded-output evidence.
4. Treat Plane's BIN failsafe evidence as authoritative for aircraft response. BIN timestamps describe logged and sampled observations; they do not establish the exact physical RF-loss instant.

Aircraft BIN evidence does not provide transmitter-side RF margin, transmitter power state, packet rate or distance.

## Optional EdgeTX CSV recording and analysis

This optional recording is a separate transmitter-side source that supplements the aircraft ground test. It does not change the physical test method or the aircraft BIN evidence.

1. Follow the transmitter recording boundary above and confirm EdgeTX CSV logging before the controlled test.
2. After the test, retain the original transmitter CSV together with its corresponding aircraft BIN. CSV clock times may differ from aircraft GPS time, so session pairing and timeline alignment require careful review.
3. In the GUI, analyse the aircraft BIN first. Then choose **Discover nearby** to inspect CSV files beside the BIN, or **Browse CSV…** to choose a file elsewhere.
4. Inspect each candidate's diagnostic hints. Choose **Auto pair** only when the application identifies exactly one eligible candidate.
5. Choose **Use selected** to explicitly associate the selected CSV with the analysed BIN. Explicit selection records the user's choice; it is not proof that the BIN and CSV belong to the same flight or session.
6. Review the reported pairing status, alignment status, telemetry availability and warnings. Distinguish session-wide RF observations from episode-specific measurements. RF observations are not necessarily measurements at the aircraft's logged failsafe boundaries.
7. Choose **Remove CSV evidence** to remove the optional transmitter evidence and return to the cached BIN-only report. This does not delete the CSV or rerun the aircraft analysis.

Missing or zero-filled transmitter telemetry is unavailable evidence, not a measured RF-link failure. Transmitter evidence must not alter the Plane failsafe episodes or aircraft response established from the BIN.
