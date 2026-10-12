"""Focused tests for the optional PySide6 desktop shell."""

import builtins
import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog

from gui import ANALYSIS_TABS, MainWindow


@pytest.fixture(scope="module")
def qt_app():
    """Provide one offscreen Qt application for this test module only."""
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


def test_window_constructs_with_expected_native_shell(window):
    assert window.windowTitle() == "ArduPilotTools"
    assert window.minimumWidth() >= 900
    assert window.minimumHeight() >= 600
    assert window.analysis_tabs.usesScrollButtons()
    assert window.source_path_edit.isReadOnly()
    assert all(window.report_for(name).isReadOnly() for name in ANALYSIS_TABS)
    assert "analysis not connected" in window.statusBar().currentMessage()


def test_expected_analysis_tabs_are_present_in_order(window):
    labels = tuple(
        window.analysis_tabs.tabText(index)
        for index in range(window.analysis_tabs.count())
    )
    assert labels == ANALYSIS_TABS


def test_bin_dialog_updates_shared_selected_file_state(
    monkeypatch,
    qt_app,
    window,
    tmp_path,
):
    selected = tmp_path / "flight.BIN"
    selected.touch()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), "ArduPilot BIN logs (*.bin *.BIN)"),
    )

    window.choose_log_button.click()
    qt_app.processEvents()

    expected = selected.resolve()
    assert window.selected_log == expected
    assert window.source_path_edit.text() == str(expected)
    assert window.source_path_edit.toolTip() == str(expected)
    assert str(expected) in window.statusBar().currentMessage()


def test_file_dialog_cancellation_preserves_previous_selection(
    monkeypatch,
    qt_app,
    window,
    tmp_path,
):
    previous = tmp_path / "previous.bin"
    previous.touch()
    window.set_selected_log(previous)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )

    window.choose_log_button.click()
    qt_app.processEvents()

    assert window.selected_log == previous.resolve()
    assert window.source_path_edit.text() == str(previous.resolve())
    assert "Selection cancelled" in window.statusBar().currentMessage()


def test_tab_switching_updates_visible_module_context(qt_app, window):
    index = ANALYSIS_TABS.index("Range-Walk Comparison")
    window.analysis_tabs.setCurrentIndex(index)
    qt_app.processEvents()

    assert window.current_analysis == "Range-Walk Comparison"
    assert window.analysis_tabs.currentWidget().isVisible()
    report = window.report_for("Range-Walk Comparison").toPlainText()
    assert "EdgeTX CSV recordings" in report
    assert "shared BIN selection does not apply" in report
    assert "analysis not connected" in window.statusBar().currentMessage()


def test_shell_interactions_do_not_import_or_execute_analyses(
    monkeypatch,
    qt_app,
    window,
    tmp_path,
):
    selected = tmp_path / "no-analysis.bin"
    selected.touch()
    imported_analysis_modules = []
    original_import = builtins.__import__

    def tracked_import(name, *args, **kwargs):
        if name == "analyses" or name.startswith("analyses."):
            imported_analysis_modules.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracked_import)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )

    window.choose_log_button.click()
    window.analysis_tabs.setCurrentIndex(ANALYSIS_TABS.index("TAKEOFF"))
    qt_app.processEvents()

    assert imported_analysis_modules == []
    assert "Analysis execution is not connected" in window.report_for(
        "TAKEOFF"
    ).toPlainText()
