# Observed plateau voltage comparison validation

Read-only pilot Battery Analysis measurement on `feat/battery-plateau-voltage-comparison`.
These are comparisons between stable observed load levels, not instantaneous
voltage sag, resistance, or a qualified low-current voltage drop. No history
recorder or persistence format was changed.

## Evidence rules

The pre-onset interval is the latest paired BAT interval ending nominally
within 0.5 s of qualified pilot T0. It spans at least 0.8 s, contains at least
nine samples, has gaps no larger than 0.25 s, and meets the specified current
and voltage ranges. A continuous rise into T0 may occur after that interval;
an invalid timestamp, missing value, gap, or return below its current level
cannot be skipped. The selected interval must have a valid paired BAT path
through the actual T0 sample, with no gap over 0.25 s. A synthetic 0.5 s
gap after a stable pre-plateau is therefore unavailable. The recency
comparison allows **1 ms** of timestamp
alignment slack: PC63 #1 ends 500.146 ms before T0 despite rounded audit
times appearing to meet the 500 ms boundary. This adjustment is smaller than
one BAT sampling period and preserves the two staged negative cases.
Synthetic boundary probes accept 500.146 ms and 501.000 ms and reject
501.001 ms.

The earliest stable higher-current interval spans at least 0.8 s within T0
through T0 + 6 s and ends no later than confirmed T1 or the selected
FlightWindow end. A flight ending 0.6 s after T0 cannot produce a loaded
plateau, even if BAT samples continue outside that flight. Its paired samples meet
the 0.25 s gap, 15%/1 A current-range, and 0.18 V voltage-range limits. Median
current must exceed both the pre-onset median by 5 A and 70% of the existing
pilot launch-current reference. All medians and intervals use logged samples.

## Five-log replay

Times are exact selected BAT endpoints in seconds since boot, rounded here to
three decimals; values are medians rounded to three decimals. The evaluator
retains full microsecond timestamps internally.

| Event | Pre interval | Pre A / V | Loaded interval | Loaded A / V | Observed ΔV |
|---|---|---|---|---|---:|
| PC61 #2 | 1079.500–1080.500 | 7.730 / 15.199 | 1081.600–1082.500 | 32.269 / 13.317 | 1.882 V |
| PC61 #3 | 1359.400–1360.300 | 0.568 / 15.197 | 1361.000–1362.000 | 31.336 / 12.987 | 2.210 V |
| PC63 #1 | 161.558–162.458 | 5.628 / 16.177 | 163.558–164.558 | 21.072 / 14.979 | 1.199 V |
| PC73 #1 | 434.020–435.020 | 12.290 / 15.511 | 437.320–438.220 | 34.952 / 13.703 | 1.808 V |
| PC73 #2 | 928.420–929.320 | 9.639 / 15.111 | 933.020–933.920 | 31.719 / 13.215 | 1.896 V |

PC63 #2 and #3: **No sufficiently recent pre-onset plateau**. Their staged
current increases still have qualified pilot T0 and observed raw extrema,
without a plateau voltage-change number.

PC61 #1 and PC74 #1 retain the separate strict low-current voltage drops of
2.30 V and 1.30 V respectively. The new comparison may also appear beside
those strict results and must not be substituted for them. Nine Piper takeoffs
and nine pilot BAT T0s remain identified; Ranger has no pilot duplicates and
retains its two AUTO measurements.

Telemetry cannot establish instantaneous cell behavior or physical touchdown.
The pre-onset and loaded plateaus may have different throttle application
stages, temperatures, and elapsed times. No automatic Pack History ingestion
is authorized by this metric.
