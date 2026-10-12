"""Focused tests for local module documentation windows."""

import os
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from gui import ANALYSIS_TABS, MainWindow
from gui.docs_viewer import DOCS_ROOT, MODULE_SLUGS, ModuleDocsWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app):
    subject = MainWindow()
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


def test_all_modules_have_working_docs_buttons_and_render_both_files(
    qt_app,
    window,
):
    assert window.selected_log is None
    assert tuple(window.docs_buttons) == ANALYSIS_TABS
    assert set(MODULE_SLUGS) == set(ANALYSIS_TABS)

    for module in ANALYSIS_TABS:
        readme_path = DOCS_ROOT / MODULE_SLUGS[module] / "README.md"
        glossary_path = DOCS_ROOT / MODULE_SLUGS[module] / "glossary.md"
        assert readme_path.is_file()
        assert glossary_path.is_file()
        assert readme_path.read_text(encoding="utf-8").strip()
        assert glossary_path.read_text(encoding="utf-8").strip()

        window.docs_buttons[module].click()
        qt_app.processEvents()
        viewer = window._docs_windows[module]
        assert viewer.module == module
        assert viewer.windowTitle() == f"{module} Documentation — ArduPlaneTools"
        assert viewer.isVisible()
        assert viewer.tabs.count() == 2
        assert viewer.tabs.tabText(0) == "README"
        assert viewer.tabs.tabText(1) == "Glossary"
        assert viewer.readme_browser.isReadOnly()
        assert viewer.glossary_browser.isReadOnly()
        assert "Documentation unavailable" not in viewer.readme_browser.toPlainText()
        assert "Documentation unavailable" not in viewer.glossary_browser.toPlainText()
        assert "<h1" in viewer.readme_browser.toHtml()
        assert "<h1" in viewer.glossary_browser.toHtml()

    assert len(window._docs_windows) == len(ANALYSIS_TABS)


def test_docs_do_not_select_a_log_change_reports_or_execute_analysis(
    qt_app,
    tmp_path,
):
    calls = []
    window = MainWindow(
        autotune_adapter=lambda path: calls.append(("AUTOTUNE", path)),
        takeoff_adapter=lambda path: calls.append(("TAKEOFF", path)),
        stall_adapter=lambda path: calls.append(("Stall", path)),
    )
    window.show()
    selected = tmp_path / "selected.bin"
    selected.touch()
    window.set_selected_log(selected)
    report = "Existing Stall report"
    window.report_for("Stall").setPlainText(report)

    window.docs_buttons["Stall"].click()
    qt_app.processEvents()

    assert calls == []
    assert window.selected_log == selected.resolve()
    assert window.report_for("Stall").toPlainText() == report
    assert window._docs_windows["Stall"].isVisible()
    window.close()
    qt_app.processEvents()
    assert window._docs_windows == {}


def test_reopening_focuses_existing_window_then_close_allows_new_window(
    qt_app,
    window,
):
    window.docs_buttons["Landing"].click()
    qt_app.processEvents()
    first = window._docs_windows["Landing"]

    window.docs_buttons["Landing"].click()
    qt_app.processEvents()
    assert window._docs_windows["Landing"] is first
    assert first.isVisible()

    first.close()
    _wait_until(qt_app, lambda: "Landing" not in window._docs_windows)
    window.docs_buttons["Landing"].click()
    qt_app.processEvents()
    second = window._docs_windows["Landing"]
    assert second is not first
    assert second.isVisible()


def test_missing_documents_render_clear_local_error(qt_app, tmp_path):
    viewer = ModuleDocsWindow("Events", docs_root=tmp_path)
    viewer.show()
    qt_app.processEvents()

    for browser in (viewer.readme_browser, viewer.glossary_browser):
        text = browser.toPlainText()
        assert "Documentation unavailable" in text
        assert "Unable to read" in text
    viewer.close()
    qt_app.processEvents()


def test_documentation_path_is_independent_of_current_working_directory(
    monkeypatch,
    qt_app,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    viewer = ModuleDocsWindow("Range-Walk Comparison")
    viewer.show()
    qt_app.processEvents()

    assert "Walk 1" in viewer.readme_browser.toPlainText()
    assert "Documentation unavailable" not in viewer.readme_browser.toPlainText()
    assert "Range-Walk glossary" in viewer.glossary_browser.toPlainText()
    viewer.close()
    qt_app.processEvents()


def test_docs_remain_available_while_analysis_worker_is_running(qt_app, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def takeoff_adapter(_path):
        started.set()
        assert release.wait(2)
        return "TAKEOFF Analysis\nNo TAKEOFF-mode executions found."

    window = MainWindow(takeoff_adapter=takeoff_adapter)
    window.show()
    selected = tmp_path / "active.bin"
    selected.touch()
    window.set_selected_log(selected)
    window.takeoff_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._analysis_thread is not None
    assert all(button.isEnabled() for button in window.docs_buttons.values())
    window.docs_buttons["Radio Link"].click()
    qt_app.processEvents()
    assert window._docs_windows["Radio Link"].isVisible()
    assert window._analysis_thread is not None

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    window.close()
    qt_app.processEvents()
