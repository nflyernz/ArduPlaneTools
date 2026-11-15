# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for the unsigned native macOS application."""

import os
from pathlib import Path


project_root = Path(SPECPATH).parent
scripts_root = project_root / "Scripts"
version = os.environ.get("APT_VERSION", "1.0.0")
macos_short_version = os.environ.get("APT_MACOS_SHORT_VERSION", version)
macos_bundle_version = os.environ.get("APT_MACOS_BUNDLE_VERSION", version)
source_commit = os.environ.get("APT_SOURCE_COMMIT", "unknown")

analysis = Analysis(
    [str(scripts_root / "gui_app.py")],
    pathex=[str(scripts_root)],
    binaries=[],
    datas=[
        (str(project_root / "Config"), "Config"),
        (str(project_root / "Docs" / "gui_help"), "Docs/gui_help"),
    ],
    hiddenimports=[
        "pymavlink.dialects.v10.ardupilotmega",
        "pymavlink.dialects.v20.ardupilotmega",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ArduPlaneTools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collected = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ArduPlaneTools",
)

application = BUNDLE(
    collected,
    name="ArduPlaneTools.app",
    icon=None,
    bundle_identifier="org.arduplanetools.app",
    info_plist={
        "CFBundleDisplayName": "ArduPlaneTools",
        "CFBundleShortVersionString": macos_short_version,
        "CFBundleVersion": macos_bundle_version,
        "APTBuildVersion": version,
        "APTSourceCommit": source_commit,
        "NSHighResolutionCapable": True,
    },
)
