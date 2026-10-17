# Stall Analysis

Stall Analysis reviews deliberate FBWA slow-flight attempts in one ArduPlane DataFlash BIN. Select an existing BIN and choose **Analyse**.

The report classifies retained attempts as **Probable demand-opposed attitude departure**, **No demonstrated departure**, **Ambiguous**, or **Rejected candidate**. It relates continuing pilot demand, FBWA target, controller command/output, measured attitude response, raw airspeed with calibration provenance, flight context, and observed recovery-control milestones. Same-flight clean-idle probable events may form a descriptive airspeed cohort only when their evidence and calibration are compatible.

A probable attitude departure does **not** prove aerodynamic stall, flow separation, exact stall onset, angle-of-attack stall, or spin entry. The analysis does not select a stall speed or recommend `AIRSPEED_STALL`, `AIRSPEED_MIN`, approach speed, or landing speed.

Commanded elevator/PWM is not physical surface feedback. Recovery observations do not assert complete recovery. Separate detected flights are never pooled.
