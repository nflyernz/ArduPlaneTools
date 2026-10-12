# APT Radio Link — Range-Walk Comparison Output Specification

**Version:** 1.0 — initial output contract for implementation, 2026-10-10
**Depends on:** `Radio_Link_Range_Walk_Comparison_Procedure.md` (field actions frozen separately)
**Status:** Initial v1 output contract, prepared for focused implementation. Engineering provenance and safety restrictions remain mandatory; this specification does not alter the validated BIN Radio Link analysis.

## 1. User question

> For two or more walks on the same physical route, did changing the receiver antenna installation improve or worsen the **observed RF performance**, especially in the marginal sections, **even when no failsafe occurred**?

**Walk 1 is both the route-establishment recording and the original-antenna baseline.** Walk 2 and all later antenna configurations are compared against Walk 1, not against the preceding walk. There is no mandatory separate reconnaissance CSV.

Two or more labelled EdgeTX CSVs are sufficient. The optional aircraft BIN adds separate ArduPlane-assessed RC-invalid/failsafe evidence; it is not a requirement for RF plots or landmark recognition. The five comparison landmarks and turnaround are selected from actual Walk 1 marks, confirmed with physical route notes, and frozen for later walks.

## 2. On-demand output: three views

### A. Test setup and run validity

One row per walk:

| Walk / role | Configuration | Markers | TX power / RF mode | RF observation coverage | Warnings |
|---|---|---:|---|---|---|
| Walk 1 — baseline | Original antenna | 5/5 confirmed | From known setting / CSV | Observed vs unavailable | No warnings or explicit notes |
| Walk 2 — comparison | Changed antenna | 5/5 confirmed | From known setting / CSV | Observed vs unavailable | No warnings or explicit notes |

Preserve source CSV path/filename and recording timestamp, labelled as a **transmitter-local clock**, not GPS. Retain Walk 1's original CSV, original antenna configuration and test settings as immutable reference evidence; later walks carry their own configurations. Record the five confirmed landmark names/physical descriptions and the safe turnaround selected after Walk 1. Distinguish unknown aircraft/packet-rate/antenna details from known values. Never infer a radio setting from telemetry fields during an unavailable interval.

### B. Comparison by physical section (primary table)

One row per **section per walk**, preferably grouped by section:

| Section | Walk | `1RSS` median | `1RSS` P10 | `RQly` P10 | `RSNR` median | Usable coverage | Longest unavailable span |
|---|---|---|---|---|---|---|---|
| 1 → 2 | Walk 1 — baseline | — | — | — | — | — | — |
| 1 → 2 | Walk 2 — comparison | — | — | — | — | — | — |
| … | Walk 1 followed by each later walk | … | … | … | … | … | … |

Display the baseline first within every section and keep it visually identified as **Walk 1**. If calculated differences (e.g. `1RSS` P10 change) are included, compute each against Walk 1 only, with units and sufficient-evidence qualifications; never silently use the immediately preceding walk as the reference.

Here **P10** means the 10th percentile of *usable logged reported values* (lower tail). Greater/less-negative `1RSS` (generally dBm), greater `RQly`, and greater `RSNR` are directionally favourable **when the measurement contexts are comparable**. Percentiles are descriptive of the logged stream, not independent RF packet samples or precise margin-to-failsafe estimates. Show sample counts and recording duration in drill-down or detail output.

**Display defaults for v1:** the columns shown in the section table above are the default summary, with **`TQly` in walk/section detail** as downlink/telemetry context, not mixed into the default uplink comparison table. Avoid a single synthetic health score or mandatory threshold at this stage.

**Coverage terminology:** time/rows with RF measurements eligible under the **existing EdgeTX parser's availability classification**, plus separate counts/durations of unavailable, partial and ambiguous evidence. Coverage is not guaranteed RF-update freshness, and absence of telemetry does not establish actual physical uplink loss. A real `RQly = 0` may be retained when the parser establishes a valid observation; do not globally discard zeros.

Do not rank an entire walk based solely on sections with materially different or unknown coverage. Show **Insufficient evidence** or **Not like-for-like** explicitly rather than silently awarding a winner. **No percentage-coverage pass/fail threshold or overall antenna winner is defined for v1**; supply numerator, denominator, duration and caveats so the operator can interpret evidence quality. A section with no usable readings is Unavailable; unlike settings are Not like-for-like.

### C. Graphical evidence (included in first useful release)

- One **RF-versus-time plot per walk** showing the reported `1RSS` trace, with physical landmark lines 1–5 and clearly **broken/shaded telemetry-unavailable intervals**. No interpolation through gaps.
- A companion `RQly` plot or clearly separate axis/panel (not an unlabeled combined scale). Optionally show `RSNR` on request.
- One **section comparison plot**, showing Walk 1 as the fixed reference alongside each later walk’s `1RSS` P10 across sections 1→2, 2→3, 3→4, 4→5. Annotate usable coverage or omit/mark insufficient sections. This plot is a section-level comparison, **not** a metre-by-metre overlay.
- Titles, axis units, actual source labels, landmark numbers/names, and source provenance must be visible. Exportable plot files are desirable; choose an output format supported by existing APT dependencies after repository inspection. No GUI is required.

The elapsed-time axis is local to each walk. Do **not** overlay samples from two walks as if equal elapsed time implied equal position. Do not convert times to distances without externally recorded distance evidence.

**Graph format for first release:** save PNG images as ordinary local output artifacts with source-derived run labels and units. Use the repository's available plotting facilities when practical; do not introduce a GUI. Report an explicit plotting error rather than silently substituting zero-filled lines.

## 3. Landmark identification and review

The parser must retain transmitter-local `Ele` independently of RF telemetry status. The October 10 marker calibration supports **+900 with a continuous hold ≥1.5 s** as an **initial candidate** for that model, subject to verifying sign/model calibration, neutral return, sample jitter, duplicate suppression and false positives. The field action remains a ~2 s full-down hold.

**Marker/window boundary convention for v1:** retain the detected full-down marker's onset and release times. The *moving section* `i → i+1` begins at the release of landmark marker `i` and ends at the onset of landmark marker `i+1` (with empty/negative windows rejected). This excludes deliberate stationary marker holds and removes ambiguity from section duration. The marker-hold interval itself may be reported in a **landmark evidence detail**: median reported `1RSS`, median reported `RQly`, availability and sample count at that physical point, clearly qualified as a brief stationary observation rather than a calibrated position measurement. If no usable samples occurred during a hold, show Unavailable. Do not interpolate RF between two landmarks.

Show detected marker times and counts for each CSV before comparison. **Walk 1 establishes the canonical five-marker route and physical turnaround:** the operator confirms the five recorded positions and their landmark descriptions before changing the antenna installation. Extra exploratory holds in Walk 1 may be explicitly excluded, but an unmarked landmark cannot be manufactured. If Walk 1 cannot supply a defensible five-marker mapping, it cannot become the comparison baseline and must be repeated with the original antenna configuration.

On Walk 2+, require mapping to the **same five fixed physical landmarks**, in order. Extra/missing/ambiguous candidates require operator resolution or an incomplete-walk report. Do not silently match by elapsed time, infer missing positions, or redefine the turnaround because reception improved.

## 4. Measurement evidence rules

1. Consume existing EdgeTX parser availability semantics; do **not** rewrite the validated BIN failsafe detector.
2. **Zero-filled RF telemetry classified unavailable is not zero signal strength.** Keep visible gaps and account for missingness.
3. Preserve distinctions among **Active**, **Partial**, **Unavailable**, and **Ambiguous** where the existing parser exposes them. Keep provenance per metric; an Active row need not imply every sensor has a valid or fresh update.
4. EdgeTX logging at ~10 Hz does **not** imply each RF field is freshly updated at 10 Hz. For v1, median/P10 summarise **eligible logged reported values** (sampled stream), not independent RF updates or independent packets. Explicitly label that basis. Retain logged-row count and observation-time coverage and the parser's availability/ambiguity flags; do not infer a true RF refresh interval from repeated values. A future validated freshness estimator may add stronger qualifications without changing the field procedure.
5. Compute sections using successive transmitter-local landmark times. No BIN clock is needed for RF comparison. If a BIN is supplied, correlate only when defensible time alignment exists, with separate confidence and limitations.
6. Mark no data as **Unavailable**, invalid source as **Skipped with reason**, and mismatched settings as **Not directly comparable**; never coerce missingness to zero.

## 5. Minimal CLI flow

1. Select **Radio Link → Range-Walk Comparison** (new on-demand function, separate from existing Radio Link BIN analysis).
2. Select **Walk 1 CSV first** and label its original receiver antenna installation as the baseline. Enter/confirm the five physically repeatable landmarks, notes and safe turnaround from its recorded elevator markers. The route-establishment walk is **the same Walk 1 baseline recording**, not a discarded preliminary walk.
3. Select one or more subsequent CSVs (`Walk 2`, `Walk 3`, ...), with changed antenna configurations and recorded test settings. Map markers to the **already frozen Walk 1 route**. Do not silently replace the baseline or compare Walk 3 only against Walk 2.
4. Show setup/coverage, section table, and visualisations with Walk 1 as a clear fixed reference. Identify skips, gaps, configuration mismatches and incomplete sections.
5. Optionally attach corresponding BIN(s), clearly separated from RF measurements; not a v1 blocker.

No database, cache, automatic session pairing, new RF detector, persistent experiment manager, or battery-history refactor in v1.

## 6. Portable tests and existing-file checks

- Calibration: `Piper Cub-2026-10-10-150619.csv` — accept the two deliberate ~2 s down holds, reject the two ~0.3–0.4 s brief down movements and the ~2.5 s full-up hold; verify observed sign for this model. **This file is only for local engineering verification, not a CI dependency.**
- Telemetry semantics: `Piper Cub-2026-10-08-112115.csv` — exercise real signal variation and long unavailable spans without plotting zero-filled gaps at zero RF values. There are no validated five-landmark markers in this file, so it must **not** be portrayed as a completed comparative walk.
- Synthetic portable tests: varying time cadence, five valid markers, optional extra Walk 1 candidates explicitly excluded, missing/extra markers, accidental short/full-up movements, marker during missing telemetry, valid `RQly=0`, zero-filled unavailable RF, partial/ambiguous metrics, different TX configurations, sections without usable data, and identical section metrics with unequal coverage. Include Walk 1 baseline + Walks 2/3 to verify both later runs reference Walk 1, and reject unqualified comparisons when Walk 1 has no defensible marker mapping.
- Never require local aircraft BINs or the two private CSVs as CI fixtures; generate compact synthetic CSV/data objects instead.

## 7. Implementation acceptance gates

- Existing Radio Link BIN output and detector behaviour unchanged.
- Walk 1 establishes five physically labelled markers and four sections from its own CSV without requiring a preliminary recording. Two synthetically generated walks correctly map them; an additional Walk 3 is compared against Walk 1, not Walk 2.
- No missing-data zero is plotted or included in RF statistics as valid signal.
- A fully missing section is **Unavailable**, not the worst recorded signal value.
- Paired sections show metrics and coverage without false precise spatial alignment.
- Graphs visibly break over telemetry gaps and label the measured metric and units.
- Existing analyser tests pass; focused new portable tests pass; local CSV checks remain optional.

**Implementation defaults fixed for v1:** use the section columns in §2B; show `TQly` in detail; report logged-value distributions and observation coverage without claiming RF update freshness; export PNG plots; use no arbitrary coverage pass/fail threshold, composite score or automatic antenna winner. Review these choices only against real-world validation evidence, not speculative redesign.
