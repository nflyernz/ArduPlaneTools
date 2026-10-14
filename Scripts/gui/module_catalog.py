"""Presentation metadata for the fixed analysis-tab catalog."""

MODULE_DESCRIPTIONS = {
    "Landing": "Review approach, preflare, flare, and landing evidence.",
    "Events": "Inspect recorded flight events.",
    "Battery": "Analyse battery consumption and electrical performance.",
    "Battery Pack Management": "Manage battery pack identities and history.",
    "Pack Performance": "Examine pack behaviour across logs.",
    "TAKEOFF": "Review takeoff triggers, execution, and outcomes.",
    "AUTOTUNE": "Examine recorded tuning sessions.",
    "Radio Link": "Inspect radio-link quality and failsafe evidence.",
    "Range-Walk Comparison": "Compare repeatable radio range-walk recordings.",
    "Stall": "Review FBWA slow-flight and probable attitude-departure evidence.",
}

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


def connection_description(module: str) -> str:
    """Describe full or intentionally partial GUI availability."""
    if module == "Range-Walk Comparison":
        return "CSV/marker preview available; comparison not yet connected"
    return (
        "Connected to the GUI"
        if module in CONNECTED_ANALYSES
        else "Not yet connected to the GUI"
    )


def connection_status(module: str) -> str:
    """Return the compact status-bar form of GUI availability."""
    if module == "Range-Walk Comparison":
        return "CSV/marker preview ready; comparison not connected"
    return "ready" if module in CONNECTED_ANALYSES else "analysis not connected"
