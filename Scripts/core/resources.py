"""Locate read-only application resources in source and frozen builds."""

import sys
from pathlib import Path


def application_resource_root() -> Path:
    """Return the root containing bundled Config and Docs resources."""
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", None)
        if root is None:
            raise RuntimeError("Frozen application resource root is unavailable")
        return Path(root)
    return Path(__file__).resolve().parents[2]


def resource_path(path: str | Path) -> Path:
    """Resolve a relative read-only resource without using the process CWD."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return application_resource_root() / candidate
