# Stall Analysis guide

APT's initial Stall Analysis examines deliberate slow-flight tests recorded in
ArduPlane DataFlash BIN logs. Select **12. Stall Analysis** in the Analyse menu
and choose one BIN log. The current prototype analyses FBWA attempts only and
reports logged evidence; it does not diagnose a confirmed aerodynamic stall.

> **Safety — deliberate stall testing is an intentional departure from normal
> controlled flight.** FBWA provides bounded attitude targets, not direct
> elevator passthrough. Full forward pitch stick requests the configured
> nose-down pitch limit; it need not command full down elevator. If actual
> pitch has already passed the configured negative limit, FBWA may command
> nose-up correction toward its allowed target. FBWA stall-mitigation features
> do not guarantee a safe stall envelope or recovery. Attempt deliberate tests
> only with adequate recovery altitude, a suitable area, and prior familiarity
> with the aircraft's stall and recovery behaviour. Know the recovery and mode
> exit procedure before the test; switching to MANUAL may be necessary if
> normal recovery control is unavailable.

FBWA is required **for this analysis** because the log can show the chain
`pilot demand → FBWA target → controller output → actual aircraft response`.
APT can therefore distinguish a pitch fall after demand was reduced from a
fall despite continuing nose-up demand. This is an analytical requirement,
not a claim that FBWA is intrinsically safer than MANUAL for full-stall tests.
`STICK_MIXING` does not provide FBWA pitch/roll control and is not a requirement
for this analysis.

## Reading an attempt

- **Probable demand-opposed attitude departure** means that logged attitude
  stopped following continuing nose-up FBWA demand in the prototype's required
  sequence. It does not prove flow separation, exact stall onset, an angle of
  attack stall, or spin entry.
- **No demonstrated departure** means a usable slow-flight test occurred, but
  the required demand-opposed signature was not demonstrated. It does not
  establish a universally safe speed.
- **Ambiguous** means a real manoeuvre lacked complete or consistent decisive
  evidence.
- **Rejected candidate** means the movement was not sufficiently supported as
  an analysable FBWA stall-test attempt.

The **pre-fall pitch-peak airspeed** is the raw airspeed sample associated with
the attitude peak before the opposed fall. **First opposed-fall airspeed** is
associated with the first observed fall while nose-up demand continued.
**Minimum usable airspeed** is the lowest suitable sample within that attempt;
it may occur at a different phase. Recovery-related airspeeds are associated
with observed control action or a later sustained speed increase. These are
distinct measurements. APT does not select one as “the stall speed.” Logged
elevator command/output endpoints describe commands and PWM output, not proof
of physical surface position or servo saturation. Recovery lines list observed
milestones; they do not assert that recovery was complete.

The report shows both **Saved airspeed ratio** from logged parameters and
**Effective airspeed ratio** inferred for the relevant raw airspeed sample when
supported. Autocalibration can change an in-memory ratio without making the
latest saved parameter identical; this was observed in the Gold Log. If runtime
calibration cannot be supported, APT says so rather than substituting the
saved ratio. Each displayed airspeed identifies its raw ARSP sensor instance
and its sample-to-event time gap.

## Reading a flight summary

Counts cover every retained classification. The **Mean pre-fall pitch-peak
airspeed** uses only comparable probable departures within the same detected
flight. Eligible attempts have clean idle-commanded throttle, approximately
level context, and compatible usable raw airspeed and calibration evidence at
the same pre-fall pitch-peak reference. The summary gives the included count,
attempt numbers, median, and range. Powered, banked, flapped, ambiguous, or
otherwise materially different attempts are excluded. Fewer than two
comparable events produce no mean. Separate detected flights are never pooled.

This is a descriptive average of logged event-linked airspeeds, not a speed
limit or parameter recommendation. APT does not automatically calculate or
recommend `AIRSPEED_STALL`, `AIRSPEED_MIN`, approach speed, or landing speed.
Those decisions require further validation, including independent Piper
testing. A future multi-log history could label an entire test session as
Clean, Half flaps, or Full flaps, with attempts inheriting that label unless
logged evidence contradicts it; session labels are not part of this version.
