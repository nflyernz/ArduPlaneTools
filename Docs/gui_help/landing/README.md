# Landing Analysis

Landing Analysis reviews landing attempts detected within ArduPlane DataFlash BIN flight windows. It accepts one BIN or a directory through the CLI workflow; this GUI tab is not yet connected to execution.

The report separates approach, preflare, flare, optional rangefinder evidence, and landing or rollout completion. Depending on available log messages, it can show approach altitude and glide slope, event times, height, airspeed, GPS groundspeed, sink rate, flare distance to the target, GPS stop, and the attempt end reason.

Values are measurements associated with logged samples and detected windows. Missing evidence is reported as unavailable. Rangefinder details appear only when suitable evidence exists.

The analysis does not certify landing safety, runway suitability, touchdown quality, or physical wheel contact. Sampling, sensor quality, configuration, wind, terrain, and the detector's evidence boundaries all affect interpretation.
