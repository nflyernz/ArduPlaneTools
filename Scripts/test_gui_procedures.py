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


def test_only_radio_link_and_stall_have_test_procedure_buttons(window):
    subject, _radio_calls, _stall_calls = window

    assert set(subject.procedure_buttons) == set(PROCEDURE_MODULES) == {
        "Radio Link",
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
                "short-failsafe response",
                "long-failsafe response",
                "Restore valid RC input",
                "does not exercise every",
                "Aircraft BIN evidence",
                "transmitter-side source",
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
