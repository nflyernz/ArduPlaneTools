# ArduPlaneTools {{TAG}} desktop preview

This prerelease provides desktop builds of ArduPlaneTools for Apple Silicon
macOS and x64 Windows. APT supports evidence-based review of ArduPlane
DataFlash logs and EdgeTX telemetry, including battery and pack history,
takeoff and landing evidence, AUTOTUNE review, stall test review, radio-link
analysis, and range-walk comparisons.

## Install on macOS Apple Silicon

Download `ArduPlaneTools-{{TAG}}-macOS-arm64.dmg`, open it, and drag
**ArduPlaneTools** to the **Applications** shortcut. The application has an
ad-hoc signature and is not notarized. macOS may require Control-clicking the
application and choosing **Open**, or approving it under **System Settings →
Privacy & Security**.

## Install on Windows x64

Download `ArduPlaneTools-{{TAG}}-Windows-x64.zip`, extract the complete
`ArduPlaneTools` directory, and run `ArduPlaneTools.exe` inside it. Keep the
directory contents together. The executable is unsigned and this preview does
not provide an installer.

## Firmware and data scope

APT requires ArduPlane 4.7.x DataFlash logs for its firmware-specific BIN-log
analyses. The takeoff semantics are based on ArduPlane 4.7.0 and checked against
the relevant unchanged ArduPlane 4.7.1 source. This does not establish support
for later firmware versions.

Historical application data is not migrated automatically. Any future
migration remains a separate, manual operation. Keep a backup before manually
moving data between installations.

## Verification

Both packages were built from source commit `{{SOURCE_COMMIT}}` in the same
workflow run. Verify the downloaded files with `SHA256SUMS.txt`:

```text
{{CHECKSUMS}}
```

The automated build validates the native packages and frozen analysis smoke
tests. This preview does not claim native interactive Windows testing or an
independent clean-machine macOS installation test.
