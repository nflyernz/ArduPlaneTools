"""Focused tests for the optional PySide6 desktop shell."""

import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog

import gui_app
from gui import ANALYSIS_TABS, MainWindow


@pytest.fixture
def window(qt_app):
    subject = MainWindow()
    subject.show()
    qt_app.processEvents()
    yield subject
    subject.close()
    qt_app.processEvents()


def test_window_constructs_with_expected_native_shell(window):
    assert window.windowTitle() == "ArduPlaneTools"
    assert window.minimumWidth() >= 900
    assert window.minimumHeight() >= 600
    assert window.analysis_tabs.usesScrollButtons()
    assert window.source_path_edit.isReadOnly()
    assert all(window.report_for(name).isReadOnly() for name in ANALYSIS_TABS)
    assert window.current_analysis == "Overview"
    assert "choose a module" in window.statusBar().currentMessage()


def test_qt_application_identity_is_arduplane_tools(monkeypatch):
    identity = {}

    class _Application:
        def __init__(self, argv):
            identity["argv"] = argv

        def setApplicationName(self, name):
            identity["application"] = name

        def setOrganizationName(self, name):
            identity["organization"] = name

        def exec(self):
            return 0

    class _Window:
        def show(self):
            identity["shown"] = True

    monkeypatch.setattr(gui_app, "QApplication", _Application)
    monkeypatch.setattr(gui_app, "MainWindow", _Window)

    assert gui_app.main(["gui_app.py"]) == 0
    assert identity == {
        "argv": ["gui_app.py"],
        "application": "ArduPlaneTools",
        "organization": "ArduPlaneTools",
        "shown": True,
    }


def test_expected_analysis_tabs_are_present_in_order(window):
    labels = tuple(
        window.analysis_tabs.tabText(index)
        for index in range(window.analysis_tabs.count())
    )
    assert labels == ("Overview", *ANALYSIS_TABS)


@pytest.mark.parametrize("filename", ("flight.bin", "flight.BIN"))
def test_bin_dialog_accepts_bin_files_and_excludes_all_files_filter(
    monkeypatch,
    qt_app,
    window,
    tmp_path,
    filename,
):
    selected = tmp_path / filename
    selected.touch()

    dialog_call = {}

    def select_file(*args, **kwargs):
        dialog_call["args"] = args
        dialog_call["kwargs"] = kwargs
        return str(selected), "ArduPilot BIN logs (*.bin *.BIN)"

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        select_file,
    )

    window.choose_log_button.click()
    qt_app.processEvents()

    file_filter = dialog_call["args"][3]
    assert file_filter == "ArduPilot BIN logs (*.bin *.BIN)"
    assert "All files" not in file_filter
    expected = selected.resolve()
    assert window.selected_log == expected
    assert window.source_path_edit.text() == str(expected)
    assert window.source_path_edit.toolTip() == str(expected)
    assert str(expected) in window.statusBar().currentMessage()
    assert window.autotune_analyse_button.isEnabled()


@pytest.mark.parametrize(
    ("rejected_name", "create_rejected", "expected_status"),
    (
        ("not-a-log.csv", "file", ".bin extension"),
        ("missing.bin", None, "not an existing file"),
        ("directory.bin", "directory", "not an existing file"),
    ),
)
def test_bin_dialog_rejection_preserves_previous_selection(
    monkeypatch,
    qt_app,
    window,
    tmp_path,
    rejected_name,
    create_rejected,
    expected_status,
):
    previous = tmp_path / "previous.bin"
    previous.touch()
    window.set_selected_log(previous)

    rejected = tmp_path / rejected_name
    if create_rejected == "file":
        rejected.touch()
    elif create_rejected == "directory":
        rejected.mkdir()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(rejected), ""),
    )

    window.choose_log_button.click()
    qt_app.processEvents()

    expected = previous.resolve()
    assert window.selected_log == expected
    assert window.source_path_edit.text() == str(expected)
    assert window.source_path_edit.toolTip() == str(expected)
    assert expected_status in window.statusBar().currentMessage()


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
    window.show_analysis_tab("Range-Walk Comparison")
    qt_app.processEvents()

    assert window.current_analysis == "Range-Walk Comparison"
    assert window.analysis_tabs.currentWidget().isVisible()
    report = window.report_for("Range-Walk Comparison").toPlainText()
    assert "EdgeTX CSV recordings" in report
    assert "shared BIN selection does not apply" in report
    assert "analysis not connected" in window.statusBar().currentMessage()


def test_shell_interactions_do_not_execute_landing_analysis(
    monkeypatch,
    qt_app,
    window,
    tmp_path,
):
    selected = tmp_path / "no-analysis.bin"
    selected.touch()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )

    window.choose_log_button.click()
    window.show_analysis_tab("Landing")
    qt_app.processEvents()

    assert "Reports use the existing Landing evidence pipeline" in window.report_for(
        "Landing"
    ).toPlainText()
