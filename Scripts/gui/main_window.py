"""Phase 1 Qt Widgets shell for ArduPlaneTools."""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.log_reader import UnsupportedFirmwareError

from .autotune_adapter import analyse_autotune_log


ANALYSIS_TABS = (
    "Landing",
    "Events",
    "Battery",
    "Battery Pack Management",
    "Pack Performance",
    "TAKEOFF",
    "AUTOTUNE",
    "Radio Link",
    "Range-Walk Comparison",
    "Stall",
)


class _AutotuneWorker(QObject):
    """Run one AUTOTUNE adapter call away from the GUI thread."""

    succeeded = Signal(str)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, log_path: Path, adapter):
        super().__init__()
        self._log_path = log_path
        self._adapter = adapter

    @Slot()
    def run(self) -> None:
        try:
            report = self._adapter(self._log_path)
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.succeeded.emit(report)
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    """Resizable desktop shell with shared source selection and analysis tabs."""

    def __init__(self, autotune_adapter=analyse_autotune_log):
        super().__init__()
        self._selected_log: Path | None = None
        self._reports: dict[str, QPlainTextEdit] = {}
        self._autotune_adapter = autotune_adapter
        self._autotune_thread: QThread | None = None
        self._autotune_worker: _AutotuneWorker | None = None
        self._close_after_worker = False
        self.autotune_analyse_button: QPushButton | None = None

        self.setWindowTitle("ArduPlaneTools")
        self.setMinimumSize(900, 600)
        self.resize(1200, 780)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        source_layout = QHBoxLayout()
        source_layout.setSpacing(8)
        source_label = QLabel("Source BIN:")
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setObjectName("sourcePath")
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("No BIN log selected")
        self.source_path_edit.setToolTip("No BIN log selected")
        self.choose_log_button = QPushButton("Choose BIN…")
        self.choose_log_button.setObjectName("chooseBinButton")
        self.choose_log_button.clicked.connect(self.choose_log)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_path_edit, 1)
        source_layout.addWidget(self.choose_log_button)
        layout.addLayout(source_layout)

        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.setObjectName("analysisTabs")
        self.analysis_tabs.setUsesScrollButtons(True)
        self.analysis_tabs.setDocumentMode(True)
        self.analysis_tabs.tabBar().setExpanding(False)
        for name in ANALYSIS_TABS:
            self.analysis_tabs.addTab(self._create_analysis_page(name), name)
        self.analysis_tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.analysis_tabs, 1)

        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(True)
        self._update_autotune_controls()
        self._update_status()

    @property
    def selected_log(self) -> Path | None:
        """Return the currently selected absolute BIN path, if any."""
        return self._selected_log

    @property
    def current_analysis(self) -> str:
        """Return the visible analysis context."""
        return self.analysis_tabs.tabText(self.analysis_tabs.currentIndex())

    def report_for(self, analysis: str) -> QPlainTextEdit:
        """Return the read-only report surface for an analysis tab."""
        return self._reports[analysis]

    def choose_log(self) -> None:
        """Select one BIN with a native dialog while preserving state on cancel."""
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select ArduPilot BIN log",
            str(self._selected_log.parent) if self._selected_log else "",
            "ArduPilot BIN logs (*.bin *.BIN);;All files (*)",
        )
        if not file_name:
            self._update_status("Selection cancelled")
            return
        self.set_selected_log(Path(file_name))

    def set_selected_log(self, path: Path) -> None:
        """Update shared source state and its full-path presentation."""
        selected = path.expanduser().resolve()
        self._selected_log = selected
        displayed = str(selected)
        self.source_path_edit.setText(displayed)
        self.source_path_edit.setToolTip(displayed)
        self.source_path_edit.setCursorPosition(0)
        self._update_autotune_controls()
        self._update_status("BIN selected")

    def start_autotune_analysis(self) -> None:
        """Validate selection and start one AUTOTUNE worker thread."""
        if self._autotune_thread is not None:
            return
        error = self._autotune_selection_error()
        if error is not None:
            self._show_autotune_error(error)
            return

        assert self._selected_log is not None
        path = self._selected_log
        thread = QThread(self)
        worker = _AutotuneWorker(path, self._autotune_adapter)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._autotune_succeeded)
        worker.failed.connect(self._autotune_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._autotune_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._autotune_thread = thread
        self._autotune_worker = worker
        self._set_autotune_busy(True)
        self.report_for("AUTOTUNE").setPlainText(
            "AUTOTUNE\n\n"
            f"Analysing {path}…\n\n"
            "The GUI remains available; no progress percentage is available."
        )
        self.statusBar().showMessage(f"AUTOTUNE analysis running — {path}")
        thread.start()

    def _create_analysis_page(self, name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        heading = QLabel(name)
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)

        if name == "AUTOTUNE":
            action_layout = QHBoxLayout()
            action_layout.addStretch(1)
            self.autotune_analyse_button = QPushButton("Analyse")
            self.autotune_analyse_button.setObjectName("autotuneAnalyseButton")
            self.autotune_analyse_button.clicked.connect(
                self.start_autotune_analysis
            )
            action_layout.addWidget(self.autotune_analyse_button)
            layout.addLayout(action_layout)

        report = QPlainTextEdit()
        report.setObjectName(f"{name.lower().replace(' ', '_')}_report")
        report.setReadOnly(True)
        report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        report.setPlainText(self._context_message(name))
        report.setToolTip("Analysis report area")
        layout.addWidget(report, 1)
        self._reports[name] = report
        return page

    @staticmethod
    def _context_message(name: str) -> str:
        if name == "Range-Walk Comparison":
            source_note = (
                "This workflow uses EdgeTX CSV recordings; the shared BIN "
                "selection does not apply."
            )
        elif name == "AUTOTUNE":
            return (
                "AUTOTUNE\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing AUTOTUNE evidence pipeline."
            )
        else:
            source_note = "Select a BIN log above to establish the shared source."
        return (
            f"{name}\n\n"
            f"{source_note}\n\n"
            "Analysis execution is not connected in GUI Phase 1."
        )

    def _on_tab_changed(self, _index: int) -> None:
        self._update_status()

    def _autotune_selection_error(self) -> str | None:
        if self._selected_log is None:
            return "Select a BIN log before running AUTOTUNE analysis."
        if self._selected_log.suffix.lower() != ".bin":
            return "The selected AUTOTUNE source must have a .bin extension."
        if not self._selected_log.is_file():
            return f"The selected BIN log does not exist: {self._selected_log}"
        return None

    def _update_autotune_controls(self) -> None:
        if self.autotune_analyse_button is None:
            return
        busy = self._autotune_thread is not None
        valid = self._autotune_selection_error() is None
        self.autotune_analyse_button.setEnabled(
            not busy and valid and not self._close_after_worker
        )
        self.choose_log_button.setEnabled(not busy and not self._close_after_worker)

    def _set_autotune_busy(self, busy: bool) -> None:
        if self.autotune_analyse_button is not None:
            self.autotune_analyse_button.setText("Analysing…" if busy else "Analyse")
        self._update_autotune_controls()

    @Slot(str)
    def _autotune_succeeded(self, report: str) -> None:
        self.report_for("AUTOTUNE").setPlainText(report)
        self.statusBar().showMessage("AUTOTUNE analysis complete")

    @Slot(object)
    def _autotune_failed(self, exc: Exception) -> None:
        if isinstance(exc, UnsupportedFirmwareError):
            message = f"Unsupported firmware.\n{exc}"
        elif isinstance(exc, OSError):
            message = f"Unable to read log: {exc}"
        else:
            message = f"AUTOTUNE analysis failed unexpectedly: {exc}"
        self._show_autotune_error(message)

    def _show_autotune_error(self, message: str) -> None:
        self.report_for("AUTOTUNE").setPlainText(
            "AUTOTUNE Analysis Error\n"
            "=======================\n"
            f"{message}"
        )
        self.statusBar().showMessage(message.replace("\n", " — "))

    @Slot()
    def _autotune_thread_finished(self) -> None:
        self._autotune_thread = None
        self._autotune_worker = None
        self._set_autotune_busy(False)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _update_status(self, action: str | None = None) -> None:
        source = str(self._selected_log) if self._selected_log else "no BIN selected"
        if self._autotune_thread is not None:
            self.statusBar().showMessage(f"AUTOTUNE analysis running — {source}")
            return
        prefix = f"{action} — " if action else ""
        state = (
            "ready"
            if self.current_analysis == "AUTOTUNE"
            else "analysis not connected"
        )
        self.statusBar().showMessage(
            f"{prefix}{self.current_analysis} — {source} — {state}"
        )

    def closeEvent(self, event) -> None:
        """Defer destruction until an active AUTOTUNE worker has exited."""
        if self._autotune_thread is not None:
            self._close_after_worker = True
            self.choose_log_button.setEnabled(False)
            if self.autotune_analyse_button is not None:
                self.autotune_analyse_button.setEnabled(False)
            self.statusBar().showMessage(
                "Waiting for AUTOTUNE analysis to finish before closing"
            )
            event.ignore()
            return
        event.accept()
