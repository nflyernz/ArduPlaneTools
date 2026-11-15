# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller definition for the unsigned native Windows x64 application."""

from pathlib import Path


project_root = Path(SPECPATH).parent
scripts_root = project_root / "Scripts"

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
    icon=None,
)

distribution = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ArduPlaneTools",
)
