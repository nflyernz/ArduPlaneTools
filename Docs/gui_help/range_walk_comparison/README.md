# Range-Walk Comparison

Range-Walk Comparison compares repeatable, transmitter-recorded EdgeTX CSV walks using five confirmed physical landmarks and four outward moving sections. It is CSV-based and the GUI tab is not yet connected; use the interactive CLI workflow.

Walk 1 is always the original-antenna baseline. Later walks retain the same landmark order. Deliberate calibrated full elevator-down holds provide marker candidates, which the user confirms rather than the tool manufacturing missing landmarks. Stationary marker holds remain separate from moving sections.

The report presents setup validity, marker mapping, eligible `1RSS`, `RQly`, and `RSNR` statistics, observed-time coverage, unavailable telemetry, and setting comparability. PNG output includes per-walk RF traces and baseline-referenced section P10 comparisons.

Missing or zero-filled telemetry is not low RF. Repeated CSV values may be held rather than independent updates. `TPWR` is reported telemetry, `RFMD` is an index, and the analysis does not infer RF margin, equal-distance positions, a Plane failsafe, or an automatic antenna winner.
