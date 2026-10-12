# TAKEOFF Analysis

TAKEOFF Analysis reviews ArduPlane TAKEOFF-mode execution evidence from one DataFlash BIN. It is connected to the GUI: select an existing BIN and choose **Analyse**.

The detector retains TAKEOFF-mode executions, firmware launch triggers, explicit already-airborne entries, throttle-suppression changes, TAKEOFF control-stage completion, mode exit, and relevant configured parameters. The performance report associates logged attitude, airspeed, groundspeed, altitude, and commanded throttle/output evidence with each owned execution. It distinguishes completed control stages from mode-exit-censored executions and reports missing evidence as unavailable.

Measurements describe logged firmware demand, estimated aircraft state, and commanded output. They do not prove physical hand release, wheel rotation, liftoff, actuator position, motor response, or thrust. A detected trigger is firmware evidence, and a command value is not physical feedback.

The report does not grade takeoff quality or recommend configuration changes. Interpret metrics with their event boundaries, sensor source, parameter history, and sampling limits.
