# Pilot-controlled takeoff evidence refinement: five-log validation

This is a read-only validation record for the uncommitted
`feat/pilot-takeoff-evidence-refinement` worktree. Times are seconds since BIN
boot, rounded to 0.01 s. The five BINs are local optional fixtures, not
independently annotated ground truth. No Pack History data was written.

## Ground-to-flight classification

| Log | Pilot events | Rejected GPS candidates | Ground-state basis |
|---|---:|---:|---|
| PC61 | 3 FBWA | 25 | Initial launch, then two inferred landings and relaunches |
| PC63 | 3 FBWA | 19 | Initial launch, then two inferred landings and relaunches; the third remains in the second FlightWindow |
| PC73 | 1 MANUAL, 1 FBWA | 1 | Initial launch, then an inferred landing and relaunch |
| PC74 | 1 FBWA | 1 | Initial launch |
| Ranger | 0 | 3 | Two AUTO launches stay on the existing AUTO path |
| **Total** | **9** | **49** | Same candidate counts as Slice 2 baseline |

The relaunch rule requires at least five seconds of recent low GPS speed,
a two-second stable local POS plateau with low speed and reduced propulsion,
and a recorded descent of at least 10 m into that plateau after prior flight.
It permits a subsequent powered taxi roll and a ground site at a different
home-relative altitude. Ground contact is inferred; none of these logs provide
a separately qualified contact sensor for this rule. `STAT.isFlying` is supporting
evidence only. An airborne episode that reproduces every ground signal could
remain indistinguishable and must be treated as a limitation of telemetry-only
classification.

A 10 Hz synthetic case with a 2–5 s fast taxi, 5–11 s settled ground interval,
and genuine climb from 11 s now produces one event at 11 s. The 2 s candidate
is rejected because GPS speed returned to a persistent ground state before
its proposed climb proof. Earlier speed without airborne altitude does not by
itself establish a prior flight. A prior confirmed event, recorded altitude
above the local ground, or an ambiguous speed dip without sustained reduced
power still requires landing proof before another launch is confirmed.

## Pilot BAT onset evidence

The pilot search examines BAT from eight seconds before to four seconds after
the GPS transition, with up to three additional seconds for a stable preceding
baseline. It chooses the earliest sustained stage reaching at least 40% of
the event-local six-second launch-current reference, with a recent stable BAT
plateau, a sustained follow-through and associated CTUN throttle. Voltage is
never used to choose T0. The 40% gate excludes low taxi stages; it is a
pilot-specific onset gate, not the shared 80% load-end threshold.
CTUN propulsion demand must span at least 0.2 s within 0.2 s before T0 through
the 0.8 s BAT rise-confirmation interval. The 0.2 s lead allowance covers
BAT–CTUN timestamp alignment; throttle ending 0.7 s before a current rise no
longer qualifies that rise. The nine real-log onset timestamps below remain
unchanged after this check.

In the table, `prior I` is the median current in the stated stable BAT window;
`T0 I` is the raw current sample at T0; `gate` is the increase required above
that prior plateau; and `follow I` is the median current through the stated
confirmation endpoint. These are observed BAT samples and thresholds, not an
inferred pre-load voltage. `response base` is independently qualified by the
unchanged Slice 1 evaluator. A dash means unavailable.

| Log | GPS / mode | T0 | Prior BAT window | Prior I | T0 I | Gate | Follow I by time | T1 | Iref | Raw peak I | Response base V/I | Min loaded V/I | Qualified drop V |
|---|---|---:|---|---:|---:|---:|---|---:|---:|---:|---|---|---:|
| PC61 #1 | 711.64 FBWA | 712.10 | 711.00–711.90 | 8.19 | 17.85 | 9.83 | 31.99 by 712.90 | 715.50 | 33.83 | 34.70 | 15.83 / 8.23 | 13.54 / 32.03 | 2.30 |
| PC61 #2 | 1081.42 FBWA | 1080.70 | 1079.40–1080.40 | 7.71 | 15.92 | 9.26 | 24.36 by 1081.50 | 1089.80 | 32.24 | 32.56 | — | 13.00 / 31.45 | — |
| PC61 #3 | 1361.68 FBWA | 1360.70 | 1359.40–1360.30 | 0.57 | 15.76 | 1.37 | 31.43 by 1361.50 | 1364.60 | 31.35 | 37.54 | — | 12.73 / 37.54 | — |
| PC63 #1 | 163.48 FBWA | 162.96 | 161.56–162.46 | 5.63 | 9.68 | 6.75 | 16.73 by 163.76 | 172.26 | 24.13 | 24.84 | — | 14.40 / 24.82 | — |
| PC63 #2 | 436.16 FBWA | 435.36 | 431.36–432.36 | 0.60 | 11.98 | 1.40 | 15.28 by 436.16 | 437.86 | 28.85 | 29.90 | — | 14.25 / 29.90 | — |
| PC63 #3 | 666.14 FBWA | 663.56 | 660.16–661.16 | 0.60 | 7.29 | 1.40 | 6.74 by 664.26 | 667.96 | 17.21 | 17.50 | — | 14.59 / 17.47 | — |
| PC73 #1 | 434.34 MANUAL | 435.12 | 433.82–434.82 | 12.29 | 15.37 | 14.74 | 15.11 by 435.82 | 444.52 | 34.90 | 40.38 | — | 13.17 / 31.91 | — |
| PC73 #2 | 929.46 FBWA | 929.42 | 927.32–928.22 | 7.70 | 13.68 | 9.24 | 29.46 by 930.12 | 935.12 | 32.06 | 34.49 | — | 13.16 / 31.07 | — |
| PC74 #1 | 148.69 FBWA | 147.61 | 146.41–147.31 | 6.04 | 8.96 | 7.25 | 10.50 by 148.31 | 155.31 | 21.24 | 22.23 | 16.12 / 6.04 | 14.82 / 22.23 | 1.30 |

All nine Piper events now have a pilot-specific qualified BAT onset, **eight
more than the prior Slice 2 search**. This does not mean nine qualified voltage
drop measurements: the unchanged evaluator finds a qualifying low-current
voltage/current baseline for only PC61 #1 and PC74 #1. For the other seven,
voltage drop remains unavailable. PC63 #3 later re-accelerates; its T1 is a
confirmed reduction, not a final load end. The T0 values need independent
review, particularly the gradual or multistage transitions. They differ from
the manual exploratory anchors in the 80% validation note because this is a
new automatic onset rule with a separately fixed six-second T0-based reference.

The Ranger AUTO regression remains at T0/T1 approximately 222.458/227.759 s
and 603.359/609.958 s. The AUTO detector and shared 0.5-second smoothing,
six-second reference, 80%/three-second reduction, 20-second fallback and
five-second follow-up rules were not changed.

If a future event lacks a defensible T0, the confirmed takeoff remains. The
report then gives a separately labelled GPS-anchored BAT interval and observed
peak current and minimum voltage with concurrent current. It does not infer
sag, T1 or recovery from that interval. Missing current or voltage samples
mark the interval partial while retaining extrema of valid samples.
