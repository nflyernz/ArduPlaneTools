"""Focused tests for the GUI module Overview page."""

import os
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QGroupBox, QLabel

from gui import ANALYSIS_TABS, MainWindow
from gui.module_catalog import MODULE_DESCRIPTIONS
from gui.pack_performance_adapter import BatteryPackPerformanceService


VISIBLE_TAB_LABELS = (
    "Overview",
    "Battery Analysis",
    "Battery Pack Management",
    "Pack Performance",
    "TAKEOFF",
    "Landing",
    "AUTOTUNE",
    "Stall",
    "Events",
    "Radio Link",
    "Range-Walk Comparison",
)


@pytest.fixture
def window(qt_app, tmp_path):
    subject = MainWindow(
        pack_performance_service=BatteryPackPerformanceService(
            pack_store_path=tmp_path / "packs.json",
            history_store_path=tmp_path / "history.json",
        )
    )
    subject.show()
    qt_app.processEvents()
    yield subject
    subject.close()
    qt_app.processEvents()


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def test_overview_is_default_and_separate_from_analysis_reports(window):
    labels = tuple(
        window.analysis_tabs.tabText(index)
        for index in range(window.analysis_tabs.count())
    )
    overview_labels = {
        label.text()
        for label in window.analysis_tabs.widget(0).findChildren(QLabel)
    }

    assert window.current_analysis == "Overview"
    assert window.analysis_tabs.currentIndex() == 0
    assert labels == VISIBLE_TAB_LABELS
    assert ANALYSIS_TABS[0] == "Battery"
    assert tuple(window._reports) == ANALYSIS_TABS
    assert "Battery" in window._reports
    assert "Battery Analysis" not in window._reports
    assert "Overview" not in window._reports
    assert "ArduPlaneTools" in overview_labels
    assert "Evidence-based ArduPlane flight-log analysis" in overview_labels
    assert "choose a module" in window.statusBar().currentMessage()


def test_overview_has_three_ordered_module_sections(window):
    page = window.analysis_tabs.widget(0)
    sections = tuple(page.findChildren(QGroupBox))
    headings = tuple(
        label.text()
        for label in page.findChildren(QLabel, "overviewSectionHeading")
    )
    expected = (
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

    assert headings == tuple(title for title, _modules in expected)
    for section, (_title, modules) in zip(sections, expected, strict=True):
        assert tuple(
            name
            for name, button in window.overview_buttons.items()
            if button.parentWidget() is section
        ) == modules


def test_every_overview_entry_describes_and_opens_its_module(qt_app, window):
    expected_descriptions = {
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

    assert tuple(window.overview_buttons) == ANALYSIS_TABS
    for name in ANALYSIS_TABS:
        button = window.overview_buttons[name]
        expected_label = "Battery Analysis" if name == "Battery" else name
        assert button.text() == expected_label
        assert button.font().pointSizeF() == pytest.approx(
            window.font().pointSizeF() + 2.0
        )
        assert button.minimumHeight() >= 70
        assert button.description() == expected_descriptions[name]
        assert "Connected to the GUI" not in button.description()
        assert "Not yet connected to the GUI" not in button.description()

        window.analysis_tabs.setCurrentIndex(0)
        button.click()
        if name == "Pack Performance":
            _wait_until(qt_app, lambda: window._analysis_thread is None)
        else:
            qt_app.processEvents()
        assert window.current_analysis == name
        assert window.analysis_tabs.currentIndex() == ANALYSIS_TABS.index(name) + 1

    range_walk_description = window.overview_buttons[
        "Range-Walk Comparison"
    ].description()
    assert range_walk_description == "Compare repeatable radio range-walk recordings."
    assert "RF comparison" not in range_walk_description


@pytest.mark.parametrize("name", ANALYSIS_TABS)
def test_module_headers_separate_context_from_empty_reports(window, name):
    page = window.analysis_tabs.widget(ANALYSIS_TABS.index(name) + 1)
    slug = name.lower().replace(" ", "_").replace("-", "_")
    title = page.findChild(QLabel, f"{slug}HeaderTitle")
    description = page.findChild(QLabel, f"{slug}HeaderDescription")
    instruction = page.findChild(QLabel, f"{slug}HeaderInstruction")
    expected_title = "Battery Analysis" if name == "Battery" else name
    expected_instruction = "Select a BIN log above, then choose Analyse."
    expected_empty_state = "No analysis run yet."
    if name == "Battery Pack Management":
        expected_instruction = (
            "Select a BIN log above to view or manage its pack association."
        )
        expected_empty_state = "No management operation run yet."
    elif name == "Pack Performance":
        expected_instruction = (
            "Select a Pack ID, then choose View report. No BIN selection is required."
        )
        expected_empty_state = "No report loaded yet."
    elif name == "Range-Walk Comparison":
        expected_instruction = (
            "Select an EdgeTX CSV to detect markers and prepare a range walk. "
            "The shared Source BIN selection does not apply."
        )
        expected_empty_state = "No CSV inspection or marker detection run yet."

    assert title.text() == expected_title
    assert description.text() == MODULE_DESCRIPTIONS[name]
    assert instruction.text() == expected_instruction
    assert window.report_for(name).toPlainText() == expected_empty_state
    assert MODULE_DESCRIPTIONS[name] not in window.report_for(name).toPlainText()


def test_battery_read_only_explanation_is_above_report(window):
    page = window.analysis_tabs.widget(ANALYSIS_TABS.index("Battery") + 1)
    note = page.findChild(QLabel, "batteryOperationalNote")

    assert "This analysis is read-only." in note.text()
    assert "Battery Pack Management" in note.text()
    assert note.text() not in window.report_for("Battery").toPlainText()


def test_navigation_preserves_selected_bin_and_existing_report(qt_app, window, tmp_path):
    selected = tmp_path / "flight.BIN"
    selected.touch()
    window.set_selected_log(selected)
    report = "AUTOTUNE Review\nLog: flight.BIN\nSessions: 1"
    window.report_for("AUTOTUNE").setPlainText(report)

    window.analysis_tabs.setCurrentIndex(0)
    window.overview_buttons["Landing"].click()
    window.analysis_tabs.setCurrentIndex(0)
    window.overview_buttons["AUTOTUNE"].click()
    qt_app.processEvents()

    assert window.selected_log == selected.resolve()
    assert window.source_path_edit.text() == str(selected.resolve())
    assert window.report_for("AUTOTUNE").toPlainText() == report


def test_overview_navigation_does_not_execute_analysis(qt_app, tmp_path):
    calls = []
    window = MainWindow(
        autotune_adapter=lambda path: calls.append(("AUTOTUNE", path)),
        takeoff_adapter=lambda path: calls.append(("TAKEOFF", path)),
        stall_adapter=lambda path: calls.append(("Stall", path)),
        landing_adapter=lambda path: calls.append(("Landing", path)),
        events_adapter=lambda path: calls.append(("Events", path)),
        battery_adapter=lambda path: calls.append(("Battery", path)),
        radio_link_adapter=lambda path: calls.append(("Radio Link", path)),
        pack_performance_service=BatteryPackPerformanceService(
            pack_store_path=tmp_path / "packs.json",
            history_store_path=tmp_path / "history.json",
        ),
    )
    window.show()
    qt_app.processEvents()

    for name in ANALYSIS_TABS:
        window.analysis_tabs.setCurrentIndex(0)
        window.overview_buttons[name].click()
        if name == "Pack Performance":
            _wait_until(qt_app, lambda: window._analysis_thread is None)
    qt_app.processEvents()

    assert calls == []
    assert "Overview" not in window._reports
    window.close()


def test_overview_remains_available_while_worker_blocks_other_analyses(
    qt_app,
    tmp_path,
):
    started = threading.Event()
    release = threading.Event()
    takeoff_calls = []
    autotune_calls = []

    def takeoff_adapter(path):
        takeoff_calls.append(path)
        started.set()
        assert release.wait(2)
        return "TAKEOFF Analysis\nNo TAKEOFF-mode executions found."

    def autotune_adapter(path):
        autotune_calls.append(path)
        return "AUTOTUNE report"

    window = MainWindow(
        autotune_adapter=autotune_adapter,
        takeoff_adapter=takeoff_adapter,
    )
    window.show()
    selected = tmp_path / "active.bin"
    selected.touch()
    window.set_selected_log(selected)
    window.takeoff_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    window.analysis_tabs.setCurrentIndex(0)
    qt_app.processEvents()
    assert window.current_analysis == "Overview"
    assert "TAKEOFF analysis running" in window.statusBar().currentMessage()

    window.overview_buttons["AUTOTUNE"].click()
    qt_app.processEvents()
    assert window.current_analysis == "AUTOTUNE"
    assert not window.autotune_analyse_button.isEnabled()
    window.autotune_analyse_button.click()
    window.start_autotune_analysis()
    assert autotune_calls == []
    assert takeoff_calls == [selected.resolve()]

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert window.autotune_analyse_button.isEnabled()
    window.close()
