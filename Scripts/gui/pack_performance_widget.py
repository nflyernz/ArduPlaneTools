"""Focused Qt controls for read-only Battery Pack Performance reporting."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .pack_performance_adapter import (
    BatteryPackPerformanceService,
    PackPerformanceIndex,
    PackPerformanceReport,
)


class PackPerformanceWidget(QWidget):
    """Pack selector, explicit report action, and read-only report surface."""

    refresh_requested = Signal()
    report_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        notice = QLabel(
            "<b>Read-only Pack Performance</b><br>"
            "Views existing Pack IDs and stored observations. This module "
            "does not modify pack identities, associations, or history."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.read_only_notice = notice

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Physical Pack ID:"))
        self.pack_selector = QComboBox()
        self.pack_selector.setObjectName("packPerformanceSelector")
        self.pack_selector.currentIndexChanged.connect(self._selection_changed)
        controls.addWidget(self.pack_selector, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("packPerformanceRefreshButton")
        self.refresh_button.clicked.connect(self.refresh_requested)
        controls.addWidget(self.refresh_button)
        self.view_button = QPushButton("View report")
        self.view_button.setObjectName("packPerformanceViewButton")
        self.view_button.clicked.connect(self._request_report)
        controls.addWidget(self.view_button)
        layout.addLayout(controls)

        self.report = QPlainTextEdit()
        self.report.setObjectName("pack_performance_report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setPlainText(
            "Pack Performance\n\n"
            "Choose a physical Pack ID, then select View report.\n\n"
            "A source BIN is not required."
        )
        layout.addWidget(self.report, 1)
        self.set_busy(False)

    @property
    def selected_pack_id(self) -> str | None:
        """Return the selected physical Pack ID, if one is available."""
        return self.pack_selector.currentText() or None

    def set_pack_ids(self, pack_ids: tuple[str, ...]) -> str:
        """Replace known IDs while retaining a still-valid selection."""
        previous = self.selected_pack_id
        self.pack_selector.blockSignals(True)
        self.pack_selector.clear()
        self.pack_selector.addItems(pack_ids)
        retained = previous in pack_ids
        if retained:
            self.pack_selector.setCurrentText(previous)
        self.pack_selector.blockSignals(False)
        self._selection_changed()
        if not pack_ids:
            message = "No known Battery Pack IDs."
            self.report.setPlainText(message)
        elif previous is not None and not retained:
            message = (
                f"Pack ID {previous} is no longer registered. "
                f"Selected {self.selected_pack_id}."
            )
            self.report.setPlainText(message)
        else:
            message = "Pack IDs and stored history refreshed."
        return message

    def set_busy(self, busy: bool, task: str | None = None) -> None:
        """Prevent overlapping storage operations and label the active one."""
        self._busy = busy
        self.pack_selector.setEnabled(not busy and self.pack_selector.count() > 0)
        self.refresh_button.setEnabled(not busy)
        self.view_button.setEnabled(
            not busy and self.pack_selector.count() > 0
        )
        self.refresh_button.setText(
            "Refreshing…" if busy and task == "refresh" else "Refresh"
        )
        self.view_button.setText(
            "Loading…" if busy and task == "report" else "View report"
        )

    def _selection_changed(self) -> None:
        self.view_button.setEnabled(
            not self._busy and self.pack_selector.count() > 0
        )

    def _request_report(self) -> None:
        pack_id = self.selected_pack_id
        if pack_id is not None:
            self.report_requested.emit(pack_id)


class PackPerformanceController:
    """Coordinate the focused widget with MainWindow's existing worker."""

    analysis_name = "Pack Performance"

    def __init__(self, service, start_worker, is_busy, show_status):
        self.service = service or BatteryPackPerformanceService()
        self.start_worker = start_worker
        self.is_busy = is_busy
        self.show_status = show_status
        self.widget: PackPerformanceWidget | None = None
        self.task: str | None = None
        self.pending_refresh = False

    def create_widget(self, parent=None) -> PackPerformanceWidget:
        """Create and connect the one Pack Performance tab surface."""
        widget = PackPerformanceWidget(parent)
        widget.refresh_requested.connect(self.request_refresh)
        widget.report_requested.connect(self.request_report)
        self.widget = widget
        return widget

    def request_refresh(self) -> None:
        """Reload persistence now, or after the current GUI task finishes."""
        if self.is_busy():
            self.pending_refresh = True
            return
        self.task = "refresh"
        self._start(None, lambda _unused: self.service.refresh())

    def request_report(self, pack_id: str) -> None:
        """Load a selected pack's report without requiring a source BIN."""
        if self.is_busy():
            return
        self.task = "report"
        self._start(pack_id, self.service.report)

    def handle_success(self, result: object) -> bool:
        """Consume Pack Performance results from the shared worker."""
        if isinstance(result, PackPerformanceIndex):
            message = self._require_widget().set_pack_ids(result.pack_ids)
        elif isinstance(result, PackPerformanceReport):
            widget = self._require_widget()
            if result.pack_id != widget.selected_pack_id:
                message = "The selected Pack ID changed; refresh and try again."
                widget.report.setPlainText(message)
            else:
                widget.report.setPlainText(result.text)
                message = f"Pack Performance report loaded for {result.pack_id}."
        else:
            return False
        self.show_status(message)
        return True

    def handle_failure(self, exc: Exception) -> None:
        """Display a storage failure without changing persistent state."""
        message = f"Unable to load Pack Performance data: {exc}"
        self._require_widget().report.setPlainText(
            "Pack Performance Error\n"
            "======================\n"
            f"{message}"
        )
        self.show_status(message)

    def set_busy(self, busy: bool) -> None:
        """Reflect the process-wide worker state in local controls."""
        if self.widget is not None:
            self.widget.set_busy(busy, self.task if busy else None)

    def worker_finished(self, was_pack_performance: bool) -> None:
        """Clear task state and service one deferred refresh."""
        if was_pack_performance:
            self.task = None
        if self.pending_refresh and not self.is_busy():
            self.pending_refresh = False
            self.request_refresh()

    def _start(self, value, adapter) -> None:
        widget = self._require_widget()
        action = "Refreshing stored history…" if self.task == "refresh" else (
            f"Loading report for {value}…"
        )
        self.start_worker(self.analysis_name, value, adapter)
        widget.report.setPlainText(f"Pack Performance\n\n{action}")
        self.show_status(action)

    def _require_widget(self) -> PackPerformanceWidget:
        assert self.widget is not None
        return self.widget
