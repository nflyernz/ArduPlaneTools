"""Persist the native BIN selection dialog's starting directory."""

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths


SETTING_KEY = "log_dialog/last_directory"


def fallback_directory() -> Path:
    """Return the first-run location for the current platform."""
    if sys.platform == "darwin":
        return Path.home() / "ArduPilotTools"
    if sys.platform == "win32":
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        return Path(location) if location else Path.home() / "Documents"
    return Path.home()


def starting_directory() -> Path:
    """Use the saved location only while it still exists."""
    saved = QSettings("ArduPlaneTools", "ArduPlaneTools").value(SETTING_KEY, "")
    directory = Path(saved).expanduser() if isinstance(saved, str) and saved else None
    return directory if directory is not None and directory.is_dir() else fallback_directory()


def remember_directory(path: Path) -> None:
    """Record a successfully selected log's parent directory."""
    QSettings("ArduPlaneTools", "ArduPlaneTools").setValue(SETTING_KEY, str(path.parent))
