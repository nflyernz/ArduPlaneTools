# APT Radio Link — RF Range-Walk Comparison Procedure

**Version:** 1.2 — field-validation clarification, 2026-10-12
**Purpose:** Compare transmitter-observed RF performance over equivalent, landmark-bounded **outbound** walking sections.
**Companion document:** [`Radio_Link_Failsafe_Test_Procedure.md`](Radio_Link_Failsafe_Test_Procedure.md) — deliberate ArduPlane RC-failsafe testing. **These are different tests.**

## 1. What this test measures

Compare marginal radio-link behaviour **before or without an ArduPlane failsafe** along the same physical walking route, using the transmitter's original, unedited EdgeTX CSV. A DataFlash BIN is optional, not a prerequisite for the range-walk comparison.

The usual comparison changes the **receiver antenna installation**, but a controlled trial may instead change **aircraft position or height**. Record the one intended difference precisely. Do not describe a receiver-location comparison as an antenna comparison; if multiple variables change, report the result as confounded rather than attributing it to one cause.

This is **not** a calibrated RF sensitivity measurement, certified safe flight range, physical receiver RF-loss detector, or deliberate failsafe exercise. Missing transmitter telemetry is not automatically a receiver failsafe.

**Critical v1 boundary:** The comparison covers the **outward walk only**. Five confirmed elevator-down markers indicate the **start, three intermediate landmarks and the turnaround**, yielding four compared sections. **The return walk is not analysed or landmarked.**

## 2. Five outward markers — route and baseline

Walk 1 both **establishes the route** and provides the **baseline**. No separate reconnaissance walk is required. Preserve its receiver configuration, aircraft position, RF settings and original CSV. Walk 2 follows the *same walking route* with the intended setup change.

| Marker | Physical location | Compared section |
|---|---|---|
| 1 | Start | — |
| 2 | First intermediate landmark | 1 → 2 |
| 3 | Second intermediate landmark | 2 → 3 |
| 4 | Third intermediate / marginal-area landmark | 3 → 4 |
| 5 | **Safe turnaround — end of analysed walk** | 4 → 5 |

Choose landmarks by **repeatable physical features**, not signal percentages; place more detail around the marginal-signal area if useful. Select a **safe** turnaround using prior observations or live RF indications, without deliberately pursuing failsafe. After Walk 1, freeze all five physical landmark identities, their order and the turnaround location for the rest of that comparison series.

Do not infer an unmarked landmark, pretend that a return marker completes the outbound sequence, or silently move the turnaround to make two recordings match. Walk 1 remains the reference; later walks are not automatically compared with the preceding walk.

## 3. Safety and consistent setup

1. **Remove the propeller, secure the aircraft and leave it disarmed.** Do not operate the motor. The separate failsafe procedure covers intentional RC loss and any arming used there; do not import those steps here.
2. Keep the transmitter antenna attached and its **orientation, carrying position, height and body shielding consistent on both outward walks**. Either shielding arrangement can be used if reproducible, but changing it between Walk 1 and Walk 2 confounds the comparison. How the transmitter is carried while returning home is not relevant to v1 analysis.
3. Use the same fixed TX power (for example 50 mW), packet rate / RF mode, telemetry settings and model. Disable dynamic transmitter power for the controlled comparison; record actual settings.
4. For an **antenna trial**, hold aircraft location, height, orientation and surroundings constant while changing only the intended receiver antenna detail. Power down before changing any antenna or coax.
5. For a **receiver-position trial**, keep the antenna arrangement unchanged and record the change in aircraft position, height, orientation, nearby objects and line of sight. Other differences may still affect results; note them rather than assuming a cause.
6. Keep the **same walking route, landmarks and turnaround**. Record relevant changes in conditions, pedestrians, vehicles, vegetation or other obstructions.

## 4. Recording each walk

1. Enable EdgeTX **SD Logs** with `Date`, `Time`, `Ele` and relevant RF telemetry columns. For this Piper model, use a **0.1-second logging interval**. The locally logged `Ele` movement can be present even when receiver telemetry disappears.
2. Start a **fresh CSV for each walk**. Wait about **5 seconds** at the start with the elevator neutral.
3. At **marker 1 (start)**, stop, hold **full elevator-down for approximately 3 seconds**, then release clearly to neutral.
4. Walk outward. At **each of markers 2, 3 and 4**, stop, hold **full elevator-down for approximately 3 seconds**, then release fully. Keep radio handling as consistent as practical.
5. At **marker 5 (turnaround)**, make the fifth full-down **3-second hold**, then release. This ends the analysed route: **do not add return-leg markers**.
6. Keep recording for about **5 seconds**, then stop the CSV. You may walk home afterwards; even if you leave logging running, the return leg is **out of scope**.
7. Retain the **original unedited CSV**. Note its exact filename and pair it with the optional BIN, if recorded. Do not erase blanks or zero placeholders in RF columns.
8. **Before altering the aircraft setup for Walk 2, check that Walk 1 really contains five accepted markers.** If a marker was too short or ambiguous, repeat Walk 1 with the original configuration. Do the same acceptance check on Walk 2.

**Marker margin matters:** The existing detector's provisional rule accepts approximately `Ele ≥ +900` for **at least 1.5 seconds**, followed by release. On 12 October 2026, a deliberately marked ~1.4-second hold was rejected, leaving Walk 1 incomplete. The new **3-second field hold** provides margin; do not loosen the detector simply to accept a bad marker.

**No invented measurements:** If RF telemetry is absent at a marker or along a section, preserve its absence. A missing RF reading is not `0 dBm`, `0%` RQly, or proof of receiver failsafe. Transmitter-local markers can remain valid during a telemetry outage.

## 5. Notes to keep with each CSV

| Field | Record |
|---|---|
| Test identity | Date, Walk 1 baseline / Walk 2 comparison, experiment (antenna change or receiver-position change) |
| Route | Five physical landmark descriptions in outbound order; exact turnaround |
| Evidence | Exact EdgeTX CSV; optional exact BIN filename |
| Aircraft and receiver | Model, receiver and receiver antenna arrangement |
| Intended variable | Antenna mounting/orientation **or** receiver location, height and orientation; measured/estimated displacement where relevant |
| Fixed settings | TX power, dynamic-power state, packet rate/RF mode, telemetry ratio if known |
| Transmitter handling | Which side carried, approximate orientation/height, whether body-shielded |
| Conditions | Weather, terrain/vegetation, nearby structures or electrical equipment, people/vehicles and other changes |
| Validation | Number of accepted markers and any rejected/extra movements |

If a BIN was collected, use it only for aircraft-side RC-input/failsafe evidence; **do not redefine BIN episodes using CSV RF dips**, nor claim precise RF minima belong to episodes without a valid alignment and freshness basis.

## 6. Acceptance and interpretation

- **Five accepted outward markers in each CSV**, correctly mapped to the same landmarks. The five markers bound **four outward sections**; the return trip is not a fifth section or an additional four sections.
- Walk 1's raw CSV and setup are retained as the baseline. Extra exploratory movements in Walk 1 require explicit operator review/mapping; none may be silently discarded to fabricate a valid walk.
- Compare corresponding sections with valid RF statistics (such as RQly, RSSI and RSNR), sample counts and usable-coverage qualifications. A section without valid RF samples is **Unavailable** rather than zero or a failure of the entire radio link.
- Missing or ambiguous markers must be reported. A partial diagnostic comparison may still help troubleshoot a recording, but it **does not validate the complete production four-section workflow**.
- Differences in RF settings, antenna handling, aircraft geometry or obstruction must be disclosed. A difference in signal strength alone does not prove its physical cause.

### Field-validation lesson: 12 October 2026

The two Piper recordings produced **3 accepted markers on Walk 1** and **4 on Walk 2**. The tool appropriately rejected the full comparison and generated no final PNGs. Two mutually bounded sections were available as diagnostic evidence, both with 100% usable RF coverage, but this **was not a complete validated five-marker comparison**. BINs separately recorded compatible short/long failsafe sequences. The missing marker was a **procedure/execution issue**, not evidence that detector thresholds should be relaxed.

## 7. Original transmitter-only marker calibration

`Piper Cub-2026-10-10-150619.csv` recorded `Ele` at approximately 10 Hz. For this transmitter/model, elevator-down was approximately **+1024**, elevator-up **−1024**, neutral near zero. Two intentional full-down holds lasted approximately **2.9 s** and **1.8 s** above +900; brief movements lasted approximately **0.4 s** and **0.3 s**. These values are **specific to this transmitter configuration**: the detector specification, not this field procedure, owns sign/threshold tolerance.

## 8. Scope boundary

This procedure deliberately uses **one baseline, one outward route, five marker holds, four compared sections and one original CSV per walk**. It does not introduce a return-leg analysis, mandatory GPS/BIN recording, deliberate ArduPlane failsafe, or automatic editing of logged telemetry. Add those only after an explicit design and implementation change.
