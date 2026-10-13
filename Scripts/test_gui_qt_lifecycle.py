"""Regression tests for deterministic Qt test-object cleanup."""

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from conftest import _close_widgets_and_drain_deletes
from gui import MainWindow


def test_cleanup_deletes_windows_before_session_application(qt_app):
    window = MainWindow()
    window.show()
    window.open_module_docs("Events")
    viewer = window._docs_windows["Events"]
    qt_app.processEvents()

    assert isValid(window)
    assert isValid(viewer)

    _close_widgets_and_drain_deletes(qt_app)

    assert QApplication.instance() is qt_app
    assert isValid(qt_app)
    assert not isValid(viewer)
    assert not isValid(window)
    assert QApplication.topLevelWidgets() == []


def test_cleanup_rejects_running_child_thread(qt_app):
    window = QWidget()
    thread = QThread(window)
    window.show()
    thread.start()

    try:
        with pytest.raises(RuntimeError, match="running QThread"):
            _close_widgets_and_drain_deletes(qt_app)
    finally:
        thread.quit()
        assert thread.wait(1_000)
        _close_widgets_and_drain_deletes(qt_app)
