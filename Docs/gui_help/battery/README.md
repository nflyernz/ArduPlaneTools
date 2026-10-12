# Battery Analysis

Battery Analysis evaluates logged electrical evidence for one detected flight and one battery-monitor instance in an ArduPlane DataFlash BIN. The GUI tab is not yet connected; the CLI workflow selects the log, flight, instance, and optional physical Pack ID.

The report includes flight duration, start/final/minimum voltage, maximum and average current, maximum power, consumed energy and capacity, and consumption rate. It also reports the highest-load observation and bounded load events such as takeoff, with pre-load voltage, minimum loaded voltage, sag, current, recovery, and configured low/critical-voltage margins where available.

Pack tracking is optional. When a log is associated with a Pack ID, supported AUTO-takeoff observations can be recorded in pack history.

Results describe logged monitor data and configured thresholds. They do not measure cell-level health, remaining capacity under every load, connector condition, or future safe endurance.
