"""Shared pytest fixtures for the optional Qt GUI tests."""

import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """Keep one QApplication strongly owned for the entire pytest process."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    _close_widgets_and_drain_deletes(app)


@pytest.fixture(autouse=True)
def _cleanup_qt_widgets(request):
    """Finish GUI object deletion before the next test starts."""
    yield
    if "qt_app" in request.fixturenames:
        _close_widgets_and_drain_deletes(request.getfixturevalue("qt_app"))


def _close_widgets_and_drain_deletes(app) -> None:
    """Close remaining top-level widgets and deliver DeferredDelete events."""
    from PySide6.QtCore import QCoreApplication, QEvent, QThread
    from PySide6.QtWidgets import QApplication

    widgets = QApplication.topLevelWidgets()
    running_threads = [
        thread
        for widget in widgets
        for thread in widget.findChildren(QThread)
        if thread.isRunning()
    ]
    if running_threads:
        raise RuntimeError("Qt test cleanup found a running QThread")

    for widget in widgets:
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
