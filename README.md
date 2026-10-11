# ArduPilotTools

ArduPilotTools is a Python toolkit for evidence-based analysis of ArduPilot
fixed-wing flight logs.

The project is currently focused on ArduPlane landing analysis. It reads
DataFlash BIN logs, identifies individual flights and AUTO landing attempts,
and reports measured and logged evidence associated with each attempt.

The longer-term goal is a modular flight-analysis framework that can support
additional analyses such as cruise performance, TECS behaviour, power systems,
RTL and autotune.

## Current Status

The project is under active development.

The current primary user-facing analysis is **Landing Analysis**.

The framework also contains an Event Timeline, Battery Analysis, sensor
processors and development/regression tools used to validate the underlying
analysis architecture.

Landing Analysis has been regression-tested against a set of development
ArduPlane 4.7 flight logs containing successful landings, aborted approaches,
multiple landing attempts, missing flare evidence and different landing
termination cases.

Raw development flight logs and aircraft parameter files are intentionally
not included in the public repository.

## Design Philosophy

The analyzer is intended to report what the flight log supports rather than
judge the quality of the flight.

The current landing analysis therefore concentrates on measured or logged
evidence such as:

- landing-attempt boundaries
- approach altitude
- glide slope
- preflare timing and height
- airspeed
- GPS groundspeed
- sink rate
- flare timing and height
- distance from the mission landing target
- rangefinder acquisition
- GPS rollout-stop evidence
- landing termination reason

Missing or ambiguous evidence is reported as unavailable rather than inferred.

Unusual telemetry is preserved as evidence rather than automatically
reinterpreted as pilot error, aircraft error or firmware error.

## Requirements

The project currently uses Python 3 and the packages listed in
`requirements.txt`.

A Python virtual environment is recommended.

Example:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running the Analyzer

From the repository root:

```bash
python Scripts/analyse.py
```

The main menu currently presents:

```text
Flight Analysis
================
1. Landing Analysis
2. Event Timeline
3. Battery Analysis
4. Cruise Analysis
5. Autotune Review
6. Sensor Diagnostics
7. Log Summary
0. Exit
```

Some menu items are placeholders for future analyses.

**12. Stall Analysis** examines FBWA slow-flight attempts in a single BIN log.
It reports demand-versus-response evidence and per-flight descriptive airspeed
statistics, without claiming a confirmed aerodynamic stall. Read the
[Stall Analysis guide](Docs/Stall_Analysis_Guide.md) and its safety warning
before using it for deliberate tests.

## Landing Analysis

Select:

```text
1. Landing Analysis
```

Landing Analysis accepts either:

- a single ArduPilot `.bin` / `.BIN` flight log; or
- a directory containing multiple `.bin` / `.BIN` flight logs.

For a single log:

```text
Log file or directory: Logs/log_19.bin
```

For an entire directory:

```text
Log file or directory: Logs/
```

When a directory is supplied, Landing Analysis processes every `.bin` and
`.BIN` log in that directory in sequence.

A single BIN log may itself contain multiple flights. Each detected flight is
analysed independently, and each flight may contain zero, one or multiple
AUTO landing attempts.

Conceptually:

```text
Directory
    |
    +-- BIN log
    |     +-- Flight 1
    |     |     +-- Landing attempt 1
    |     |     +-- Landing attempt 2
    |     |
    |     +-- Flight 2
    |           +-- Landing attempt 1
    |
    +-- BIN log
    |     +-- Flight 1
    |           +-- Landing attempt 1
    |
    +-- ...
```

This allows the same analysis workflow to be used for an individual flight log
or for batch analysis of a collection of logs.

## Example Landing Output

A landing attempt is presented in sections similar to:

```text
FLIGHT 1
======================================================================

Landing 1 Attempt 1
----------------------------------------------------------------------

Landing window              11:57.705 -> 12:23.104
Landing duration            25.4 s

APPROACH

Approach altitude           20.5 m
Glide slope                 3.9 deg

PREFLARE

Time                        12:15.904
Preflare height             4.9 m
Airspeed                    11.0 m/s
GPS groundspeed             11.1 m/s
Sink rate                   1.5 m/s

FLARE

Time                        12:16.404
Flare-timing height         4.6 m
Sink rate                   1.6 m/s
Airspeed                    11.5 m/s
GPS groundspeed             11.5 m/s
Flare distance to target    45.8 m

RANGEFINDER

First non-zero              12:08.925
First distance              11.7 m
First in range              12:09.023
In-range distance           5.8 m
Continuous from             12:12.184

LANDING / ROLLOUT COMPLETION

GPS stop                    12:23.104
Flare -> stop               6.7 s
Distance from target        19.1 m
End reason                  GPS stop
```

Values are derived from the evidence available in the log. Optional evidence
such as airspeed or rangefinder data is not required for the landing attempt
itself to be detected.

## Landing Attempt Detection

Landing attempts are detected within an already identified flight.

The detector uses logged ArduPlane landing state and associated flight evidence
to establish bounded AUTO landing attempts.

A landing attempt can terminate for different logged or measured reasons,
including:

- an aborted landing
- leaving the landing state
- a mode transition
- disarm where applicable
- a persistent low-GPS-speed rollout stop
- the end of the parent flight window

The termination reason is retained as part of the analysis evidence.

GPS stop represents landing/rollout completion. It is not labelled as
touchdown.

## Mission Landing Target

Where the log contains a complete and unambiguous mission snapshot, Landing
Analysis can associate the applicable `MAV_CMD_NAV_LAND` target with an attempt.

This allows the analyzer to report measurements such as:

```text
Flare distance to target
Distance from target
```

Mission data is treated conservatively. If the applicable mission snapshot is
missing, incomplete or ambiguous, target-dependent measurements are left
unavailable rather than selecting a target by assumption.

## Rangefinder Evidence

Rangefinder data is optional.

Where available, Landing Analysis reports evidence including:

- first non-zero measurement
- first measurement within the configured usable range
- distance at acquisition
- beginning of continuous rangefinder data

Rangefinder telemetry is reported as logged evidence. It is not required for
landing-attempt detection.

This distinction is useful when investigating unusual rangefinder behaviour
during the transition into the sensor's usable range.

## Parameter Files

The framework supports companion parameter files for parameter-dependent
analysis.

The current parameter model is log-wide. A companion parameter file represents
the parameter snapshot associated with that log.

Parameter files used during development are not included in the public
repository.

A future version may reconstruct parameter state from in-log parameter changes
where per-flight parameter history is required.

## Architecture

The core architecture separates source telemetry, flight scope, evidence
processing and analysis.

```text
BIN log
   |
   v
FlightReader
   |
   v
FlightLog
   |
   +-- telemetry
   +-- parameters
   +-- events
   +-- mode segments
   +-- metadata
          |
          v
   FlightWindow(s)
          |
          v
   analysis-specific windows
          |
          v
   processors / detectors
          |
          v
      analysis
          |
          v
        result
```

`FlightLog` owns decoded source telemetry.

`FlightWindow` defines the bounds of an individual flight without taking
ownership of that telemetry.

Analysis-specific windows such as `LandingWindow` are children of a
`FlightWindow`.

Processors and detectors provide scoped evidence. Analysis modules combine that
evidence into results.

This structure is intended to allow future analyses to reuse the same decoded
flight data without duplicating the log-reading and flight-scoping framework.

## Repository Structure

The main project areas are:

```text
Config/
    analysis configuration

Docs/
    architecture, validation, roadmap and historical implementation plans

Scripts/
    analyse.py              application entry point
    analyses/               user-facing analyses
    core/                   flight-data and evidence-processing framework
    test_*.py               development and regression harnesses
```

Local flight logs are deliberately excluded from Git:

```text
Logs/
```

Generated analysis output is also not maintained as source material in the
repository.

## Validation

Development uses both focused harnesses and regression tests.

Two important regression commands are:

```bash
python Scripts/test_landing_regression.py
python Scripts/test_event_timeline.py
```

The landing regression covers established development cases including:

- multiple flights within a BIN log
- multiple landing attempts within a flight
- aborted landing attempts
- attempts with no logged flare
- GPS-stop completion
- flight-window-ended attempts
- optional airspeed data
- optional rangefinder data
- mission target distance
- incomplete mission snapshots

The Event Timeline regression validates established event extraction across the
development log set.

A general syntax check can also be run with:

```bash
python -m compileall -q Scripts
```

See `Docs/Validation.md` for the project's validation approach.

## Documentation

Additional project documentation is under `Docs/`.

Important documents include:

```text
Docs/Architecture.md
Docs/Validation.md
Docs/ArduPlane_Analyzer_Roadmap.md
Docs/Implementation/v0.5-plan-final.md
```

Older roadmaps and implementation plans are retained as historical development
records.

## Current Development Direction

Landing Analysis is the first substantial analysis built on the framework.

Current and future work is tracked in:

```text
Docs/ArduPlane_Analyzer_Roadmap.md
```

The broader direction is to retain the same evidence-first architecture while
adding other useful fixed-wing analyses.

Potential future areas include:

- TECS behaviour
- cruise performance
- RTL
- power-system analysis
- autotune review
- richer reporting
- graphical presentation

These are development directions rather than promises of currently available
functionality.

## Privacy

ArduPilot BIN logs can contain precise GPS coordinates and other information
about an aircraft and its operating location.

For that reason, the project's development BIN logs and companion parameter
files are intentionally excluded from the public repository.

Users should consider the contents of their own flight logs before publishing
or sharing them.

## Project Scope

ArduPilotTools is an independent analysis project.

It is intended to help inspect and understand evidence recorded by ArduPilot
flight logs. It does not replace ArduPilot's own documentation, ground-control
software, flight testing or appropriate operational judgement.

The project is currently focused on ArduPlane 4.7.x development logs.
