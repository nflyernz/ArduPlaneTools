# AUTOTUNE Review

AUTOTUNE Review examines authoritative tuning-session evidence in one ArduPlane DataFlash BIN. It is connected to the GUI: select an existing BIN and choose **Analyse**.

The report identifies sessions, start and end positions, duration, termination reason, configured and selected axes, axes with observed tuning activity, flight-window association, configuration values, demand periods, action transitions, runtime gains, gain-limit events, completion milestones, and save/restore evidence where supported. Evidence warnings remain attached to the relevant session.

The analysis reports what the firmware logged. A selected axis without tuning activity is distinguished from an active axis, and an incomplete or interrupted session is not promoted to a normal completion. Runtime gain observations are not automatically equivalent to saved parameter values.

The review does not judge tuning quality, recommend gains, or guarantee that a tune was safely flown or persisted. Missing records and unsupported firmware limit what can be concluded.
