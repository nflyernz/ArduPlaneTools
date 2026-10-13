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
