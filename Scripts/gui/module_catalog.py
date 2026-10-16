"""Presentation metadata for the fixed analysis-tab catalog."""

MODULE_DESCRIPTIONS = {
    "Battery": (
        "Examine battery consumption, voltage sag and electrical loads in the "
        "selected log."
    ),
    "Battery Pack Management": "Manage pack identities and log associations.",
    "Pack Performance": "Compare battery-pack performance across logs.",
    "TAKEOFF": "Review launch triggers and takeoff performance.",
    "Landing": "Review approach, preflare, flare and landing evidence.",
    "AUTOTUNE": "Examine tuning sessions and saved gains.",
    "Stall": (
        "Review FBWA slow-flight and probable attitude-departure evidence."
    ),
    "Radio Link": "Inspect radio-link quality and failsafe evidence.",
    "Range-Walk Comparison": "Compare repeatable radio range-walk recordings.",
    "Events": "Inspect the chronological flight event timeline.",
}

MODULE_DISPLAY_LABELS = {
    "Battery": "Battery Analysis",
}

OVERVIEW_SECTIONS = (
    (
        "Battery & packs",
        ("Battery", "Battery Pack Management", "Pack Performance"),
    ),
    (
        "Flight analysis",
        ("TAKEOFF", "Landing", "AUTOTUNE", "Stall", "Events"),
    ),
    (
        "Radio & diagnostics",
        ("Radio Link", "Range-Walk Comparison"),
    ),
)

PACK_ID_PLACEHOLDER = "— Select Pack ID —"

CONNECTED_ANALYSES = frozenset(
    (
        "Landing",
        "Events",
        "Battery",
        "Battery Pack Management",
        "Pack Performance",
        "Radio Link",
        "AUTOTUNE",
        "TAKEOFF",
        "Stall",
    )
)

EXECUTABLE_ANALYSES = CONNECTED_ANALYSES - {
    "Battery Pack Management",
    "Pack Performance",
    "Radio Link",
}


def display_label(module: str) -> str:
    """Return user-facing text without changing the stable module identifier."""
    return MODULE_DISPLAY_LABELS.get(module, module)


def connection_status(module: str) -> str:
    """Return the compact status-bar form of GUI availability."""
    if module == "Range-Walk Comparison":
        return (
            "CSV preview, saved baselines and additional-walk preparation ready; "
            "RF comparison not connected"
        )
    return "ready" if module in CONNECTED_ANALYSES else "analysis not connected"
