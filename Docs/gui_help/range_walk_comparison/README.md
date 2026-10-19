# Range-Walk Comparison

Range-Walk Comparison lets you record and compare radio-link performance along the same walking route using EdgeTX telemetry CSV files.

**Walk 1 establishes the baseline.** It records your original radio configuration and five physical landmarks, dividing the outward route into four sections. Later walks repeat the same route and landmarks with a changed radio configuration, such as a different receiver antenna or antenna placement.

The module has three pages:

- **CSV & Markers:** Select an EdgeTX CSV and detect elevator-stick holds used to mark the five landmarks.
- **Walk Setup & Landmarks:** Name the landmarks, record the radio configuration and RF settings, then save Walk 1 or an additional walk.
- **History & Comparison:** View saved baselines and their associated walks, including confirmed and missing landmark markers.

For reliable comparisons, keep the route, landmarks, transmitter RF settings and other test conditions as consistent as possible. Record exactly what changes between walks.

Each saved walk preserves its original CSV evidence. Missing markers can be recorded in additional walks rather than guessed or assigned automatically.

The GUI **History & Comparison** page reconstructs section statistics and RF plots from the checksum-verified CSV copies saved with each baseline and additional walk. Select a baseline and one associated walk, then choose **Compare selected walks**. Missing telemetry remains unavailable evidence rather than zero signal, and saved settings inherited from Walk 1 are not independent confirmation of the later walk's settings.

See **Test Procedure** for instructions on recording and saving your walks.
