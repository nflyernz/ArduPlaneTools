"""Focused tests for Radio Link and Stall procedure windows."""

import os
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton
from shiboken6 import isValid

from gui import MainWindow
from gui.docs_viewer import DOCS_ROOT, PROCEDURE_MODULES


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


@pytest.fixture
def window(qt_app):
    radio_calls = []
    stall_calls = []
    subject = MainWindow(
        radio_link_adapter=lambda path: radio_calls.append(path),
        stall_adapter=lambda path: stall_calls.append(path),
    )
    subject.show()
    qt_app.processEvents()
    yield subject, radio_calls, stall_calls
    subject.close()
    qt_app.processEvents()


def test_only_documented_field_modules_have_test_procedure_buttons(window):
    subject, _radio_calls, _stall_calls = window

    assert set(subject.procedure_buttons) == set(PROCEDURE_MODULES) == {
        "Radio Link",
        "Range-Walk Comparison",
        "Stall",
    }
    for module in PROCEDURE_MODULES:
        subject.show_analysis_tab(module)
        page = subject.analysis_tabs.currentWidget()
        labels = [button.text() for button in page.findChildren(QPushButton)]
        assert "Docs" in labels
        assert "Test Procedure" in labels
        assert labels.index("Docs") < labels.index("Test Procedure")


@pytest.mark.parametrize(
    ("module", "required_text"),
    [
        (
            "Radio Link",
            (
                "Safe preparation",
                "Isolate propulsion",
                "Recording boundaries",
                "fresh flight-controller power-on session",
                "fresh transmitter power-on and CSV-logging session",
                "Do not combine recordings across power cycles",
                "CSV logging stops at shutdown",
                "separate transmitter session",
                "no continuous transmitter telemetry",
                "do not prove that a BIN and CSV belong",
                "short-failsafe response",
                "long-failsafe response",
                "Restore valid RC input",
                "does not exercise every",
                "Aircraft BIN evidence",
                "transmitter-side source",
                "Optional EdgeTX CSV recording and analysis",
                "Discover nearby",
                "Auto pair",
                "exactly one eligible candidate",
                "Use selected",
                "not proof that the BIN and CSV belong",
                "pairing status",
                "alignment status",
                "not necessarily measurements",
                "Remove CSV evidence",
                "not a measured RF-link failure",
            ),
        ),
        (
            "Range-Walk Comparison",
            (
                "Safe ground preparation",
                "isolate propulsion",
                "Do not arm the aircraft",
                "fresh EdgeTX CSV-logging session",
                "original receiver antenna installation",
                "Walk 1 is the baseline",
                "separate reconnaissance walk is not required",
                "five safe physical landmarks",
                "Landmark 5 is the safe turnaround",
                "full elevator-down position",
                "Return the elevator stick to neutral",
                "do not manufacture a missing marker",
                "must not be assumed to have equal distance",
                "not measured poor signal",
                "CSV and marker preview",
                "calibration clues only",
                "Candidate detection does not confirm",
            ),
        ),
        (
            "Stall",
            (
                "Before flight / Recovery requirements",
                "Use FBWA",
                "tested MANUAL mode switch",
                "minimum recovery-altitude limit",
                "Do not continue holding nose-up demand",
                "restore stable airspeed and attitude",
                "does not itself prove or guarantee recovery",
                "does not by itself prove an aerodynamic stall",
            ),
        ),
    ],
)
def test_procedure_opens_directly_without_bin_or_analysis_dispatch(
    qt_app,
    window,
    module,
    required_text,
):
    subject, radio_calls, stall_calls = window
    original_report = subject.report_for(module).toPlainText()
    subject.show_analysis_tab(module)

    subject.procedure_buttons[module].click()
    qt_app.processEvents()

    viewer = subject._procedure_windows[module]
    text = viewer.browser.toPlainText()
    assert subject.selected_log is None
    assert radio_calls == []
    assert stall_calls == []
    assert subject.report_for(module).toPlainText() == original_report
    assert viewer.isVisible()
    assert viewer.windowTitle() == f"{module} Test Procedure — ArduPlaneTools"
    assert viewer.browser.isReadOnly()
    assert "Documentation unavailable" not in text
    assert all(expected in text for expected in required_text)


def test_procedure_files_are_local_nonempty_markdown():
    for module, slug in (("Radio Link", "radio_link"), ("Stall", "stall")):
        path = DOCS_ROOT / slug / "procedure.md"
        text = path.read_text(encoding="utf-8")
        assert path.is_file()
        assert text.startswith("# ")
        assert len(text.splitlines()) > 20


def test_radio_link_procedure_keeps_aircraft_and_transmitter_sessions_separate():
    text = (DOCS_ROOT / "radio_link" / "procedure.md").read_text(
        encoding="utf-8"
    )

    assert "**Aircraft BIN session:**" in text
    assert "power down the aircraft safely to end that session" in text
    assert "**EdgeTX CSV session:**" in text
    assert "transmitter is safely powered down" in text
    assert "Do not combine recordings across power cycles" in text
    assert "recording made after restarting the transmitter" in text
    assert "no continuous transmitter telemetry across the power-off interval" in text
    assert "boundaries alone do not prove that a BIN and CSV belong" in text


def test_docs_and_procedure_windows_coexist_and_retain_separate_identity(
    qt_app,
    window,
):
    subject, _radio_calls, _stall_calls = window

    subject.docs_buttons["Radio Link"].click()
    subject.procedure_buttons["Radio Link"].click()
    qt_app.processEvents()
    docs = subject._docs_windows["Radio Link"]
    procedure = subject._procedure_windows["Radio Link"]

    assert docs is not procedure
    assert docs.isVisible() and procedure.isVisible()
    assert docs.tabs.count() == 2
    assert "Radio Link Analysis" in docs.readme_browser.toPlainText()
    assert "Radio Link ground-test procedure" in procedure.browser.toPlainText()

    subject.docs_buttons["Radio Link"].click()
    subject.procedure_buttons["Radio Link"].click()
    qt_app.processEvents()
    assert subject._docs_windows["Radio Link"] is docs
    assert subject._procedure_windows["Radio Link"] is procedure


def test_procedure_close_removes_reference_and_main_close_closes_all(
    qt_app,
    window,
):
    subject, _radio_calls, _stall_calls = window
    subject.procedure_buttons["Stall"].click()
    qt_app.processEvents()
    first = subject._procedure_windows["Stall"]

    first.close()
    _wait_until(qt_app, lambda: "Stall" not in subject._procedure_windows)
    subject.procedure_buttons["Stall"].click()
    subject.docs_buttons["Stall"].click()
    qt_app.processEvents()
    second = subject._procedure_windows["Stall"]
    docs = subject._docs_windows["Stall"]

    assert second is not first
    subject.close()
    qt_app.processEvents()
    assert subject._procedure_windows == {}
    assert subject._docs_windows == {}
    assert not isValid(second)
    assert not isValid(docs)


def test_range_walk_procedure_closes_and_reopens_without_bin(qt_app, window):
    subject, radio_calls, stall_calls = window
    button = subject.procedure_buttons["Range-Walk Comparison"]

    button.click()
    qt_app.processEvents()
    first = subject._procedure_windows["Range-Walk Comparison"]
    assert subject.selected_log is None
    assert "Range-Walk Comparison field-test procedure" in (
        first.browser.toPlainText()
    )
    assert radio_calls == [] and stall_calls == []

    first.close()
    _wait_until(
        qt_app,
        lambda: "Range-Walk Comparison" not in subject._procedure_windows,
    )
    button.click()
    qt_app.processEvents()
    second = subject._procedure_windows["Range-Walk Comparison"]
    assert second is not first
    assert second.isVisible()
