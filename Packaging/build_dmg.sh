#!/bin/sh
set -eu

build_root=${APT_BUILD_ROOT:-/tmp/ArduPlaneTools-macos-build}
app_path="$build_root/dist/ArduPlaneTools.app"
release_dir="$build_root/release"
architecture=$(uname -m)
artifact_version=${APT_ARTIFACT_VERSION:-preview}
dmg_name="ArduPlaneTools-${artifact_version}-macOS-${architecture}.dmg"
dmg_path="$release_dir/$dmg_name"
dmg_temp="$release_dir/.ArduPlaneTools-${artifact_version}-macOS-${architecture}.tmp.dmg"
staging_dir=
mount_dir=
mounted=0

fail() {
    echo "Error: $*" >&2
    exit 1
}

cleanup() {
    if [ "$mounted" -eq 1 ] && [ -n "$mount_dir" ]; then
        hdiutil detach "$mount_dir" >/dev/null 2>&1 || true
    fi
    if [ -n "$staging_dir" ]; then
        rm -rf "$staging_dir"
    fi
    if [ -n "$mount_dir" ]; then
        rmdir "$mount_dir" >/dev/null 2>&1 || true
    fi
    rm -f "$dmg_temp"
}

trap cleanup EXIT HUP INT TERM

[ "$(uname -s)" = "Darwin" ] || fail "DMG creation requires macOS."
[ "$architecture" = "arm64" ] || fail "This preview DMG targets arm64; detected $architecture."
[ -d "$app_path" ] || fail "Application bundle not found at $app_path"
[ -x "$app_path/Contents/MacOS/ArduPlaneTools" ] || fail "Application executable is missing."
file "$app_path/Contents/MacOS/ArduPlaneTools" | grep -q 'arm64' || fail "Application executable is not arm64."

codesign --verify --deep --strict "$app_path" || fail "Application signature verification failed before DMG creation."
source_cdhash=$(codesign -dv --verbose=4 "$app_path" 2>&1 | awk -F= '/^CDHash=/{print $2; exit}')
[ -n "$source_cdhash" ] || fail "Unable to read the application signature hash."

mkdir -p "$release_dir"
staging_dir=$(mktemp -d "$build_root/dmg-staging.XXXXXX")
mount_dir=$(mktemp -d "$build_root/dmg-mount.XXXXXX")

ditto "$app_path" "$staging_dir/ArduPlaneTools.app"
ln -s /Applications "$staging_dir/Applications"

rm -f "$dmg_temp"
hdiutil create \
    -volname "ArduPlaneTools Preview" \
    -srcfolder "$staging_dir" \
    -fs HFS+ \
    -format UDZO \
    -ov \
    "$dmg_temp"

[ -f "$dmg_temp" ] || fail "Disk image was not created at $dmg_temp"
hdiutil verify "$dmg_temp"
hdiutil attach -readonly -nobrowse -mountpoint "$mount_dir" "$dmg_temp" >/dev/null
mounted=1

[ -d "$mount_dir/ArduPlaneTools.app" ] || fail "Mounted image does not contain ArduPlaneTools.app."
[ -L "$mount_dir/Applications" ] || fail "Mounted image does not contain the Applications symlink."
[ "$(readlink "$mount_dir/Applications")" = "/Applications" ] || fail "Applications symlink has an unexpected target."
entry_count=$(find "$mount_dir" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')
[ "$entry_count" -eq 2 ] || fail "Mounted image contains unexpected top-level entries."

codesign --verify --deep --strict "$mount_dir/ArduPlaneTools.app" || fail "Mounted application signature verification failed."
mounted_cdhash=$(codesign -dv --verbose=4 "$mount_dir/ArduPlaneTools.app" 2>&1 | awk -F= '/^CDHash=/{print $2; exit}')
[ "$mounted_cdhash" = "$source_cdhash" ] || fail "Application signature changed during DMG creation."

hdiutil detach "$mount_dir" >/dev/null
mounted=0
mv -f "$dmg_temp" "$dmg_path"

echo "Built and verified $dmg_path"
echo "Mounted contents: ArduPlaneTools.app, Applications -> /Applications"
echo "Application CDHash: $source_cdhash"
