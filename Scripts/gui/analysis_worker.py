"""Shared one-shot Qt worker used by connected GUI analyses."""

from PySide6.QtCore import QObject, Signal, Slot


class AnalysisWorker(QObject):
    """Run one adapter call away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, task_input, adapter):
        super().__init__()
        self._task_input = task_input
        self._adapter = adapter

    @Slot()
    def run(self) -> None:
        try:
            report = self._adapter(self._task_input)
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.succeeded.emit(report)
        finally:
            self.finished.emit()
