# macOS preview packaging

The published Apple Silicon desktop preview is available from the
[v1.1.0-beta.1 release](https://github.com/nflyernz/ArduPlaneTools/releases/tag/v1.1.0-beta.1).
End users should normally download its DMG; the commands below are for
building packages from source.

The macOS preview is a native Apple Silicon application distributed in a compressed, read-only disk image. It is not signed with a Developer ID and is not notarized. PyInstaller applies an ad-hoc signature so macOS can validate the bundle's internal consistency.

## Build the application

The application build uses a dedicated virtual environment and writes generated files outside the repository. From the repository root, run:

```sh
Packaging/build_macos.sh
```

The application is created at:

```text
/tmp/ArduPlaneTools-macos-build/dist/ArduPlaneTools.app
```

To use another temporary build location, set `APT_BUILD_ROOT` for both build commands:

```sh
APT_BUILD_ROOT=/path/to/build Packaging/build_macos.sh
```

## Build and validate the disk image

With the application already built, run:

```sh
Packaging/build_dmg.sh
```

Or use the same custom build root:

```sh
APT_BUILD_ROOT=/path/to/build Packaging/build_dmg.sh
```

By default the script creates `release/ArduPlaneTools-preview-macOS-arm64.dmg`
under the build root. In the versioned GitHub release workflow,
`APT_ARTIFACT_VERSION=v1.1.0-beta.1` produces
`ArduPlaneTools-v1.1.0-beta.1-macOS-arm64.dmg`. It verifies the disk image, mounts it read-only, checks that it contains only `ArduPlaneTools.app` and an `Applications` symlink, verifies the mounted application, compares its signature hash with the source bundle, and safely detaches it.

## Install the preview manually

1. Double-click the downloaded DMG (for example,
   `ArduPlaneTools-v1.1.0-beta.1-macOS-arm64.dmg`) in Finder.
2. Drag **ArduPlaneTools.app** onto the **Applications** shortcut in the disk-image window.
3. Wait for copying to finish, then eject **ArduPlaneTools Preview** in Finder.
4. Open the Applications folder and start **ArduPlaneTools**.

Because this preview has no Developer ID signature and is not notarized, macOS Gatekeeper may refuse the first launch. Do not disable Gatekeeper. Instead, Control-click **ArduPlaneTools** in Applications, choose **Open**, and confirm **Open**. If macOS does not offer that choice, open **System Settings → Privacy & Security** and use **Open Anyway** for ArduPlaneTools after the blocked launch.

This preview is published for Apple Silicon (`arm64`) only; Intel Macs are
unsupported. The published beta has passed local installation and real-log
checks on macOS, including the first-launch Privacy & Security approval.
Developer ID signing and notarization are deferred. Do not disable Gatekeeper.
