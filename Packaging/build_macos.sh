#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd)

python_bin=${PYTHON_BIN:-python3.13}
build_root=${APT_BUILD_ROOT:-/tmp/ArduPlaneTools-macos-build}
venv_dir=${APT_PACKAGING_VENV:-/tmp/ArduPlaneTools-pyinstaller-venv}
work_dir="$build_root/work"
dist_dir="$build_root/dist"
export PYINSTALLER_CONFIG_DIR="$build_root/pyinstaller-config"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This build script supports macOS only." >&2
    exit 1
fi

if [ ! -x "$venv_dir/bin/python" ]; then
    "$python_bin" -m venv "$venv_dir"
fi

"$venv_dir/bin/python" -m pip install \
    --requirement "$script_dir/requirements-macos-build.txt"

mkdir -p "$build_root"
{
    echo "application=ArduPlaneTools"
    echo "architecture=$(uname -m)"
    echo "macos=$(sw_vers -productVersion)"
    echo "python=$($venv_dir/bin/python --version 2>&1)"
    echo "pyinstaller=$($venv_dir/bin/pyinstaller --version)"
} > "$build_root/build-info.txt"

"$venv_dir/bin/pyinstaller" \
    --noconfirm \
    --clean \
    --workpath "$work_dir" \
    --distpath "$dist_dir" \
    "$script_dir/ArduPlaneTools.spec"

echo "Built $dist_dir/ArduPlaneTools.app"
