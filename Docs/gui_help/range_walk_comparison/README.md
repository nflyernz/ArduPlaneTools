# Range-Walk Comparison

Range-Walk Comparison compares repeatable, transmitter-recorded EdgeTX CSV walks using five confirmed physical landmarks and four outward moving sections. The GUI currently provides two setup pages: **CSV & Markers** and **Walk 1 — Baseline & Landmarks**. Later walks and RF comparison remain available only through the interactive CLI workflow.

In the GUI, choose one EdgeTX CSV and use **Auto** to examine both higher and lower `Ele` deflections. Auto estimates a dominant sustained neutral value and sustained endpoints, runs the existing marker detector in both available directions, and prefers a direction only when it has a clearly stronger sequence of complete holds and neutral returns. It does not assume that five markers must exist.

Use **Inverse** to inspect the direction opposite Auto's preferred direction. When Auto cannot establish a clear preference, it chooses deterministically, reports the ambiguity, and Inverse still selects the opposite direction. An isolated minimum or maximum and a brief stick movement are not accepted as sustained markers.

The normal GUI workflow has no manual neutral or near-down calibration. It retains the existing 87.5% full-down threshold and minimum hold duration, while accepting a neutral return within 33% of the estimated neutral-to-endpoint span. The established CLI calibration and its 20% neutral tolerance remain unchanged.

Page 1 reports the radio-local recording span, row count, and every complete elevator-down hold found by the existing detector. After detection, choose **Next: Walk 1 Setup** to use those exact detected markers; the GUI does not redetect them with different calibration settings.

On Page 2, describe the original receiver antenna installation and name five physical landmarks. The required name for landmark 5 describes the safe turnaround; there is no separate turnaround field. Exactly five detected candidates are preselected chronologically. If extra candidates exist, exclude them by selecting five distinct candidates in increasing order without reordering them. Fewer than five candidates cannot establish a complete baseline, and the GUI never manufactures a missing marker.

Optional RF Settings record the operator's configured TX power, packet rate, RF mode/band and dynamic-power state. Unknown settings are retained, with a warning that unknown or mismatched settings prevent later like-for-like RF comparison claims. Telemetry-reported TPWR or RFMD is not substituted for configured settings.

**Save Walk 1 in session** validates and retains the source CSV, exact detected marker objects, chronological mapping, physical names, landmark 5 turnaround, antenna description and optional operator-entered RF settings in memory only. It writes no project or history file. Page navigation preserves the draft; changing the CSV, Auto/Inverse direction or marker detection invalidates a saved baseline tied to older evidence.

Preview candidates are not confirmed physical landmarks until the operator maps and saves them on Page 2. Loading one CSV does not calculate RF section evidence, infer distance or failsafe behavior, or compare antennas. Missing or zero-filled RF telemetry does not affect elevator marker detection.

Walk 1 is always the original-antenna baseline. Later walks retain the same landmark order. Deliberate calibrated full elevator-down holds provide marker candidates, which the user confirms rather than the tool manufacturing missing landmarks. Stationary marker holds remain separate from moving sections.

The report presents setup validity, marker mapping, eligible `1RSS`, `RQly`, and `RSNR` statistics, observed-time coverage, unavailable telemetry, and setting comparability. PNG output includes per-walk RF traces and baseline-referenced section P10 comparisons.

Missing or zero-filled telemetry is not low RF. Repeated CSV values may be held rather than independent updates. `TPWR` is reported telemetry, `RFMD` is an index, and the analysis does not infer RF margin, equal-distance positions, a Plane failsafe, or an automatic antenna winner.
