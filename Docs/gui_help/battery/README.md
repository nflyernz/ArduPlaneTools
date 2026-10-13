# Battery Analysis

Battery Analysis evaluates logged electrical evidence for detected flights and battery-monitor instances in an ArduPlane DataFlash BIN. Select one BIN in the GUI and choose **Analyse** to review each detected flight and monitor instance in order.

The report includes flight duration, start/final/minimum voltage, maximum and average current, maximum power, consumed energy and capacity, and consumption rate. It also reports the highest-load observation and bounded load events such as takeoff, with pre-load voltage, minimum loaded voltage, sag, current, recovery, and configured low/critical-voltage margins where available.

GUI Battery Analysis is permanently read-only. It does not prompt for Pack IDs, fingerprint the BIN, change log associations or read or write battery history. Use the GUI **Battery Pack Management** tab for explicitly confirmed Pack ID changes and explicit whole-BIN AUTO takeoff history recording.

Results describe logged monitor data and configured thresholds. They do not measure cell-level health, remaining capacity under every load, connector condition, or future safe endurance.
