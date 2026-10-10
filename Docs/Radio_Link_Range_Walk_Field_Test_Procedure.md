# APT Radio Link — Range-Walk Field-Test Procedure

**Version:** 1.1.1 — distinct from deliberate failsafe test (clarification), 2026-10-10
**Scope:** Repeated, landmark-marked ground walks to compare receiver antenna installations using transmitter-local EdgeTX CSV logging.
**Status:** Field procedure frozen for first implementation and trials, including the rule that Walk 1 both establishes the route and supplies the antenna-comparison baseline. Marker thresholds and output calculations are specified separately.

## 1. Objective

Compare **marginal RF behaviour before a failsafe** over the **same physical sections** of a walking route. Changes in receiver antenna mounting or orientation are the main test variable. A walk with no ArduPlane failsafe is still useful.

The ground walk is not a calibrated RF sensitivity test, absolute range certification, physical RF-loss detector, or autonomous-flight experiment. The field procedure does not require an ArduPilot BIN.

**Separate procedure:** `Radio_Link_Test_Procedure.md` is the existing controlled **failsafe** test, which includes deliberate transmitter-off and link-loss actions, and may require aircraft arming under its specified safety precautions. **Do not apply those arming, deliberate link-loss, or long-failsafe steps to this antenna comparison.** Range-Walk Comparison uses a disarmed aircraft, no motor operation, no required BIN, and a safe turnaround informed by marginal RF observations rather than intentional failsafe. These two procedures have different purposes and must remain separate.

## 2. Walk 1 establishes the route and baseline

**Walk 1, with the original receiver antenna installation, is the baseline for every subsequent antenna comparison.** It also establishes the walking route. A separate reconnaissance walk is **not** mandatory.

During Walk 1, identify and mark **five physical landmarks** along the outward route, including the start and a safe turnaround. Use the existing Radio Link test observations and any usable live RF indications to inform where marginal reception occurs and where to turn around; do **not** deliberately pursue a failsafe or unsafe conditions. Record enough physical description to repeat the exact locations later.

The intended comparison is **five confirmed landmarks defining four sections**:

| Marker | Description to record | Comparison section |
|---|---|---|
| 1 | Start | — |
| 2 | First reference landmark | 1 → 2 |
| 3 | Transition/obstruction landmark | 2 → 3 |
| 4 | Marginal-area landmark | 3 → 4 |
| 5 | Walk 1 selected safe turnaround (fixed thereafter) | 4 → 5 |

Use marginal RF evidence to **choose** locations, but define each landmark by a **repeatable physical feature**, not a signal threshold. Prefer more landmark resolution in the weak-signal region. Distances are optional notes; software must not invent them.

After Walk 1, review its marked locations and route notes and **freeze the five landmark identities, their order, and the turnaround point** before changing the antenna installation. If Walk 1 contains extra exploratory elevator markers, retain them in the original CSV; explicitly select the five physical markers that constitute the route and exclude the extras from comparison. Do not infer an unmarked point or silently reassign an unclear marker. If no defensible five-marker mapping exists, repeat the original-antenna baseline walk before comparisons.

**Only the outward route, confirmed marker 1 through marker 5, belongs to the v1 comparison.** Walking home after marker 5 is outside the analysis, even if the CSV continues recording. The physical route and turnaround remain fixed for Walk 2 and later walks, even if another antenna performs better.

## 3. Safety and comparable setup

1. Place and secure the aircraft in the same position, height, orientation and local surroundings for every walk. Keep it **disarmed** and **remove the propeller**. Do not run the motor.
2. Ensure the transmitter antenna is attached before transmitting. Use the same transmitter antenna orientation, carrying position and approximate body orientation on each walk.
3. Fix TX power (e.g. 50 mW), packet rate / RF mode, telemetry settings and other radio configuration across walks; turn off dynamic TX power for controlled comparisons. Record actual settings rather than assuming fields recovered from intermittent telemetry are reliable.
4. Use the **original receiver antenna installation for Walk 1**; change **only the intended receiver antenna variable** for Walk 2 and later. Power down the receiver/aircraft before altering antennas or coax. Note any unavoidable differences (weather, vehicles, people, obstructions, route).
5. Choose a safe pedestrian route and turnaround. Never require a receiver failsafe or continuation into unsafe terrain to establish the endpoint.

## 4. Walk recording — operator actions

1. Confirm EdgeTX **SD Logs** is active, `Ele` is present in the chosen model's CSV and the interval is **0.1 seconds**. A receiver link is needed to measure RF but **not** to record transmitter-local elevator movement.
2. Start a fresh EdgeTX CSV. Remain at the start for approximately **5 seconds** with elevator neutral.
3. At **landmark 1**, stop, hold **full elevator-down for about 2 seconds**, and release to neutral. Keep the transmitter in its normal carrying position.
4. On **Walk 1**, progress along the route, identifying physical landmarks and an informed, safe turnaround. On **later walks**, repeat the frozen route. At **each landmark (2–5)** stop, repeat the **2-second full-down hold**, release, then continue. Aim for exactly five markers; additional exploratory Walk 1 markers require explicit operator review before using the run as baseline.
5. After landmark 5, keep logging for approximately **5 seconds**, then stop the recording. If the return is logged, it is explicitly out of scope after marker 5.
6. Retain the **original unedited CSV** and label the run `Walk 1 — Baseline (original antenna)`, `Walk 2 — Vertical antenna`, etc. Do not trim missing or zero-filled telemetry intervals manually.
7. **After Walk 1 and before altering antennas**, confirm which recorded marks correspond to the five physical landmarks, write brief route notes, and fix the turnaround for subsequent tests. If the comparison tool is not yet available, keep these notes alongside the CSV for later import.

If receiver telemetry vanishes, **still record the landmark movement**: `Ele` comes from the radio's locally sampled control, not the receiver telemetry. Do not interpret missing RF measurements as zero signal or a demonstrated ArduPlane failsafe.

## 5. Minimum notes accompanying each CSV

| Field | Example or instruction |
|---|---|
| Route / landmarks | Five landmark names and physical descriptions, in order; freeze from Walk 1 for all later walks |
| Walk number / role | `Walk 1 — Baseline`, `Walk 2 — changed antenna`, etc.; do not silently change the baseline |
| Walk label | `Original mount`, `Vertical mount` |
| Turnaround selection | Physical location and any relevant marginal RF observations during Walk 1; not an unmeasured range limit |
| CSV filename | Original EdgeTX filename |
| Aircraft / receiver | Aircraft name, RX setup if known |
| Receiver antenna configuration | Mounting position, orientation and any changed antenna |
| TX setup | TX power, dynamic-power state, packet rate / RF mode, telemetry ratio if known |
| Fixed geometry | Aircraft position/orientation, TX handling assumptions |
| Conditions / departures | Obstructions, weather or anything changed between runs |
| Optional BIN | Exact filename if available; not required |

## 6. Acceptance of a recorded walk

- **Walk 1 is the required reference**: it must use the original antenna installation, retain its raw CSV and settings, and supply a defensible mapping of the five fixed route markers. There is no mandatory separate route-establishment walk.
- All Walk 2+ comparisons are explicitly **against Walk 1**, never automatically against the preceding walk; antenna/configuration differences are recorded.
- A CSV has usable **Date/Time**, `Ele`, and the relevant RF columns or reports missing RF fields explicitly.
- There are **five confirmed full-down landmark markers**, in the expected order. Walk 1 may contain additional exploratory candidates, but the operator must explicitly map/exclude them; the software must not infer an omitted marker.
- A section with no usable RF readings is reported **Unavailable**, not `0 dBm`, `0%`, or a failed walk. Other usable sections remain reportable.
- Incomplete or ambiguous marker sequences are **flagged for review**, not silently re-numbered or stretched to make runs match.
- Walks with differing TX power or packet rate may be shown, but **not unqualified as like-for-like antenna comparisons**.

## 7. Already completed transmitter-only marker calibration

`Piper Cub-2026-10-10-150619.csv` established a locally recorded `Ele` channel sampled at approximately 10 Hz. For this model/log, elevator-down was approximately **+1024**, up approximately **−1024**, neutral near zero. Two intentional full-down holds lasted approximately **2.9 s** and **1.8 s** above +900; two brief movements lasted approximately **0.4 s** and **0.3 s**. This supports the 2-second field action, **not** a universal hardcoded detector sign or threshold. The separate design/output specification owns detection tolerance and ambiguity handling.

## 8. Freeze boundary

The frozen field-test contract is: **Walk 1 both establishes the route and records the original-antenna baseline; no mandatory separate reconnaissance; one fixed outward route after Walk 1; five confirmed physical markers and an informed, safe turnaround; one full elevator-down hold of approximately two seconds at each; one original CSV per walk; consistent RF configuration; all subsequent walks compared against Walk 1 across four bounded sections; optional BIN**.

Do not add extra-channel setup, mandatory GPS, deliberate failsafe, manual CSV editing, or turnaround/return analysis to v1 without revising this procedure. The marker algorithm and RF statistics are separate engineering choices and may be improved without changing the user's field actions.
