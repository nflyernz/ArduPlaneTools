# Stall / slow-flight test procedure

This procedure supports the Stall Analysis evidence model for deliberate FBWA slow-flight tests. It does not establish a universal stall speed, and a detected attitude departure does not by itself prove an aerodynamic stall.

## Before flight / Recovery requirements

> **Complete these requirements before beginning any slow-flight test.**

- Use **FBWA** for the slow-flight evidence intended for this analysis.
- Establish and verify a tested **MANUAL** mode switch before testing. Define a deliberate recovery plan appropriate to the aircraft and conditions.
- Establish sufficient starting altitude and a conservative minimum recovery-altitude limit before beginning. The pilot must choose these for the aircraft, site, weather and test plan; ArduPlaneTools does not prescribe a universal value.
- Stop slow-flight testing and initiate the planned recovery if the aircraft approaches that limit or if control becomes uncertain.
- Do not continue holding nose-up demand into an uncontrolled departure.
- Following an attempted departure, restore stable airspeed and attitude, then reassess the aircraft and remaining safety margin before considering another test.
- Switching modes does not itself prove or guarantee recovery. The pilot must confirm that stable controlled flight has actually been restored.

## Test preparation

1. Review the aircraft, control setup, centre of gravity, weather, test area and applicable operating rules.
2. Brief the intended FBWA entry, demand, termination cues, MANUAL recovery action and altitude limits.
3. Confirm that control surfaces, airspeed instrumentation where fitted, mode selection and logging are operating normally.
4. Establish stable flight with sufficient height and space for the planned test and recovery. Confirm that DataFlash logging is active.

## FBWA slow-flight evidence

1. Enter FBWA and establish the intended starting condition without abrupt control inputs.
2. Reduce energy progressively while monitoring attitude, airspeed evidence, control response and altitude margin.
3. If an attitude departure is observed, release the test demand and execute the established recovery plan.
4. Confirm stable airspeed and attitude after recovery. Reassess conditions and safety margins before any further attempt.

## After flight

1. Retain the corresponding DataFlash BIN and note the aircraft configuration and any relevant test observations.
2. Open **Stall** in ArduPlaneTools, select the BIN and choose **Analyse**.
3. Review probable demand-opposed attitude departures, ambiguous or no-demonstrated-departure outcomes, rejected candidates, calibration provenance, recovery observations and same-flight comparisons with their stated limitations.

The report characterises logged flight evidence. It does not certify stall behaviour, prescribe a safe operating speed, or replace flight-test planning and pilot judgement.
