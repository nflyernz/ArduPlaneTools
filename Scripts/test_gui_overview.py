"""Focused tests for the GUI module Overview page."""

import os
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel

from gui import ANALYSIS_TABS, MainWindow
from gui.pack_performance_adapter import BatteryPackPerformanceService


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
    assert labels == ("Overview", *ANALYSIS_TABS)
    assert tuple(window._reports) == ANALYSIS_TABS
    assert "Overview" not in window._reports
    assert "ArduPlaneTools" in overview_labels
    assert "Evidence-based ArduPlane flight-log analysis" in overview_labels
    assert "choose a module" in window.statusBar().currentMessage()


def test_every_overview_entry_describes_and_opens_its_module(qt_app, window):
    expected_descriptions = {
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

    assert tuple(window.overview_buttons) == ANALYSIS_TABS
    for name in ANALYSIS_TABS:
        button = window.overview_buttons[name]
        assert button.text() == name
        assert button.font().pointSizeF() == pytest.approx(
            window.font().pointSizeF() + 2.0
        )
        assert button.minimumHeight() >= 84
        assert expected_descriptions[name] in button.description()
        expected_connection = (
            "Connected to the GUI"
            if name
            in (
                "Landing",
                "Events",
                "Battery",
                "Battery Pack Management",
                "Pack Performance",
                "Radio Link",
                "Range-Walk Comparison",
                "AUTOTUNE",
                "TAKEOFF",
                "Stall",
            )
            else "Not yet connected to the GUI"
        )
        assert expected_connection in button.description()

        window.analysis_tabs.setCurrentIndex(0)
        button.click()
        if name == "Pack Performance":
            _wait_until(qt_app, lambda: window._analysis_thread is None)
        else:
            qt_app.processEvents()
        assert window.current_analysis == name
        assert window.analysis_tabs.currentIndex() == ANALYSIS_TABS.index(name) + 1


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
