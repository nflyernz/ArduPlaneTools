"""Platform-specific writable application-data paths."""

import os
import sys
from collections.abc import Mapping
from pathlib import Path


APPLICATION_DIRECTORY = "ArduPlaneTools"


def application_data_directory(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    """Return the user-writable data directory without creating it."""
    platform_name = sys.platform if platform_name is None else platform_name
    environ = os.environ if environ is None else environ
    home_path = Path.home() if home is None else Path(home)

    if platform_name == "darwin":
        return home_path / "Library/Application Support" / APPLICATION_DIRECTORY

    if platform_name == "win32":
        local_app_data = environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is unavailable")
        base = Path(local_app_data)
        if not base.is_absolute():
            raise RuntimeError("LOCALAPPDATA must be an absolute path")
        return base / APPLICATION_DIRECTORY

    if platform_name.startswith("linux"):
        xdg_data_home = environ.get("XDG_DATA_HOME")
        if xdg_data_home and Path(xdg_data_home).is_absolute():
            base = Path(xdg_data_home)
        else:
            base = home_path / ".local/share"
        return base / APPLICATION_DIRECTORY

    raise RuntimeError(f"Unsupported application-data platform: {platform_name}")
