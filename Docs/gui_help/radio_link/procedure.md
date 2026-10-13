# Radio Link ground-test procedure

This procedure gathers controlled aircraft-side RC-failsafe evidence for Radio Link Analysis. It is a ground test. Adapt the preparation to the aircraft, site, firmware configuration and operator responsibilities.

## Safe preparation

1. Secure the aircraft in a clear test area and keep people away from control surfaces and propulsion.
2. Isolate propulsion so that an unexpected output cannot produce thrust. Removing the propeller is the preferred physical isolation where practical; follow the aircraft's electrical and battery safety procedures.
3. Confirm that the flight controller, receiver and transmitter installation are complete and powered as intended for the test.
4. Verify the configured Plane RC-failsafe settings, including the short and long timeout and action settings applicable to the installed firmware. Record any settings needed to interpret the test.
5. Establish a valid RC link and confirm normal control input before interrupting it.
6. If the intended evidence requires an armed state, arm only after propulsion is physically isolated and all ground-test precautions are in place. Radio Link Analysis preserves armed, disarmed and unknown states separately.

## Controlled interruption

1. Start one clean DataFlash BIN recording and allow the aircraft to establish normal RC input.
2. Deliberately interrupt RC input using the planned test method.
3. Observe the configured short-failsafe response and, if the test plan calls for it, maintain the interruption long enough to observe the configured long-failsafe response.
4. Record observable mode changes or messages without relying on them as the only evidence. The BIN analysis associates logged RCI2, MSG and MODE evidence according to their separate meanings.
5. Restore valid RC input deliberately and confirm that control input and the expected flight mode have recovered before ending the recording.
6. Disarm where applicable, power down safely and retain the single corresponding BIN session.

Transmitter shutdown is one controlled way to interrupt RC input. It does not exercise every interference, antenna, receiver, protocol or partial-link failure mode and must not be treated as a complete RF-system qualification.

## Analyse the BIN

1. Open **Radio Link** in ArduPlaneTools and select the recorded BIN.
2. Choose **Analyse** and review the summary first.
3. Open **Show detailed evidence** to inspect sampled RC-input invalid boundaries, short and long failsafe messages, mode response, recovery, timing qualifications and commanded-output evidence.
4. Treat Plane's BIN failsafe evidence as authoritative for aircraft response. BIN timestamps describe logged and sampled observations; they do not establish the exact physical RF-loss instant.

Aircraft BIN evidence does not provide transmitter-side RF margin, transmitter power state, packet rate or distance. Optional EdgeTX CSV evidence is a separate transmitter-side source and is currently available through the CLI workflow, subject to its pairing and alignment requirements.
