"""Phase 1 Qt Widgets shell for ArduPlaneTools."""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCommandLinkButton,
    QFileDialog,
    QGridLayout,
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
from .docs_viewer import ModuleDocsWindow
from .events_adapter import analyse_events_log
from .landing_adapter import analyse_landing_log
from .stall_adapter import analyse_stall_log
from .takeoff_adapter import analyse_takeoff_log


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

_MODULE_DESCRIPTIONS = {
    "Landing": "Review approach, preflare, flare, and landing evidence.",
    "Events": "Inspect recorded flight events.",
    "Battery": "Analyse battery consumption and electrical performance.",
    "Battery Pack Management": "Manage battery pack identities and history.",
    "Pack Performance": "Examine pack behaviour across logs.",
    "TAKEOFF": "Review takeoff triggers, execution, and outcomes.",
    "AUTOTUNE": "Examine recorded tuning sessions.",
    "Radio Link": "Inspect radio-link quality and failsafe evidence.",
    "Range-Walk Comparison": "Compare repeatable radio range-walk recordings.",
    "Stall": "Review FBWA slow-flight and probable attitude-departure evidence.",
}

_CONNECTED_ANALYSES = frozenset(
    ("Landing", "Events", "AUTOTUNE", "TAKEOFF", "Stall")
)


class _AnalysisWorker(QObject):
    """Run one analysis adapter call away from the GUI thread."""

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

    def __init__(
        self,
        autotune_adapter=analyse_autotune_log,
        takeoff_adapter=analyse_takeoff_log,
        stall_adapter=analyse_stall_log,
        landing_adapter=analyse_landing_log,
        events_adapter=analyse_events_log,
    ):
        super().__init__()
        self._selected_log: Path | None = None
        self._reports: dict[str, QPlainTextEdit] = {}
        self.overview_buttons: dict[str, QCommandLinkButton] = {}
        self.docs_buttons: dict[str, QPushButton] = {}
        self._docs_windows: dict[str, ModuleDocsWindow] = {}
        self._autotune_adapter = autotune_adapter
        self._takeoff_adapter = takeoff_adapter
        self._stall_adapter = stall_adapter
        self._landing_adapter = landing_adapter
        self._events_adapter = events_adapter
        self._analysis_thread: QThread | None = None
        self._analysis_worker: _AnalysisWorker | None = None
        self._active_analysis: str | None = None
        self._close_after_worker = False
        self.autotune_analyse_button: QPushButton | None = None
        self.takeoff_analyse_button: QPushButton | None = None
        self.stall_analyse_button: QPushButton | None = None
        self.landing_analyse_button: QPushButton | None = None
        self.events_analyse_button: QPushButton | None = None

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
        self.analysis_tabs.addTab(self._create_overview_page(), "Overview")
        for name in ANALYSIS_TABS:
            self.analysis_tabs.addTab(self._create_analysis_page(name), name)
        self.analysis_tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.analysis_tabs, 1)

        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(True)
        self._update_analysis_controls()
        self._update_status()

    @property
    def _autotune_thread(self) -> QThread | None:
        """Expose the active AUTOTUNE thread for existing lifecycle tests."""
        if self._active_analysis == "AUTOTUNE":
            return self._analysis_thread
        return None

    @property
    def _autotune_worker(self) -> _AnalysisWorker | None:
        """Expose the active AUTOTUNE worker for existing lifecycle tests."""
        if self._active_analysis == "AUTOTUNE":
            return self._analysis_worker
        return None

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

    def show_analysis_tab(self, analysis: str) -> None:
        """Navigate from Overview to an existing analysis tab."""
        self.analysis_tabs.setCurrentIndex(ANALYSIS_TABS.index(analysis) + 1)

    def open_module_docs(self, module: str) -> None:
        """Open or focus the retained documentation window for one module."""
        existing = self._docs_windows.get(module)
        if existing is not None:
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return

        viewer = ModuleDocsWindow(module, self)
        viewer.destroyed.connect(
            lambda _object=None, name=module: self._docs_windows.pop(name, None)
        )
        self._docs_windows[module] = viewer
        viewer.show()

    def choose_log(self) -> None:
        """Select one BIN with a native dialog while preserving state on cancel."""
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select ArduPilot BIN log",
            str(self._selected_log.parent) if self._selected_log else "",
            "ArduPilot BIN logs (*.bin *.BIN)",
        )
        if not file_name:
            self._update_status("Selection cancelled")
            return

        selected_log = Path(file_name).expanduser().resolve()
        if not selected_log.is_file():
            self._update_status(f"Selection rejected: not an existing file: {selected_log}")
            return
        if selected_log.suffix.lower() != ".bin":
            self._update_status("Selection rejected: file must have a .bin extension")
            return

        self.set_selected_log(selected_log)

    def set_selected_log(self, path: Path) -> None:
        """Update shared source state and its full-path presentation."""
        selected = path.expanduser().resolve()
        self._selected_log = selected
        displayed = str(selected)
        self.source_path_edit.setText(displayed)
        self.source_path_edit.setToolTip(displayed)
        self.source_path_edit.setCursorPosition(0)
        self._update_analysis_controls()
        self._update_status("BIN selected")

    def start_autotune_analysis(self) -> None:
        """Start AUTOTUNE through the shared background execution path."""
        self._start_analysis("AUTOTUNE", self._autotune_adapter)

    def start_takeoff_analysis(self) -> None:
        """Start TAKEOFF through the shared background execution path."""
        self._start_analysis("TAKEOFF", self._takeoff_adapter)

    def start_stall_analysis(self) -> None:
        """Start Stall through the shared background execution path."""
        self._start_analysis("Stall", self._stall_adapter)

    def start_landing_analysis(self) -> None:
        """Start Landing through the shared background execution path."""
        self._start_analysis("Landing", self._landing_adapter)

    def start_events_analysis(self) -> None:
        """Start Event Timeline through the shared background execution path."""
        self._start_analysis("Events", self._events_adapter)

    def _start_analysis(self, analysis: str, adapter) -> None:
        """Validate the shared source and run one analysis at a time."""
        if self._analysis_thread is not None:
            return
        error = self._selection_error(analysis)
        if error is not None:
            self._show_analysis_error(analysis, error)
            return

        assert self._selected_log is not None
        path = self._selected_log
        thread = QThread(self)
        worker = _AnalysisWorker(path, adapter)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._analysis_succeeded)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._analysis_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._analysis_thread = thread
        self._analysis_worker = worker
        self._active_analysis = analysis
        self._set_analysis_busy(True)
        self.report_for(analysis).setPlainText(
            f"{analysis}\n\n"
            f"Analysing {path}…\n\n"
            "The GUI remains available; no progress percentage is available."
        )
        self.statusBar().showMessage(f"{analysis} analysis running — {path}")
        thread.start()

    def _create_overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(6)

        title = QLabel("ArduPlaneTools")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 5)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("Evidence-based ArduPlane flight-log analysis")
        layout.addWidget(subtitle)

        modules = QGridLayout()
        modules.setHorizontalSpacing(10)
        modules.setVerticalSpacing(6)
        for index, name in enumerate(ANALYSIS_TABS):
            connection = (
                "Connected to the GUI"
                if name in _CONNECTED_ANALYSES
                else "Not yet connected to the GUI"
            )
            button = QCommandLinkButton(
                name,
                f"{_MODULE_DESCRIPTIONS[name]}\n{connection}",
            )
            button.setObjectName(
                f"overview_{name.lower().replace(' ', '_').replace('-', '_')}"
            )
            button_font = button.font()
            button_font.setPointSizeF(button_font.pointSizeF() + 2.0)
            button.setFont(button_font)
            button.setMinimumHeight(84)
            button.clicked.connect(
                lambda _checked=False, analysis=name: self.show_analysis_tab(analysis)
            )
            modules.addWidget(button, index // 2, index % 2)
            self.overview_buttons[name] = button
        layout.addLayout(modules)
        layout.addStretch(1)
        return page

    def _create_analysis_page(self, name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        heading = QLabel(name)
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        docs_button = QPushButton("Docs")
        docs_button.setObjectName(
            f"{name.lower().replace(' ', '_').replace('-', '_')}DocsButton"
        )
        docs_button.clicked.connect(
            lambda _checked=False, module=name: self.open_module_docs(module)
        )
        action_layout.addWidget(docs_button)
        self.docs_buttons[name] = docs_button

        if name in _CONNECTED_ANALYSES:
            analyse_button = QPushButton("Analyse")
            analyse_button.setObjectName(f"{name.lower()}AnalyseButton")
            if name == "Landing":
                self.landing_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_landing_analysis)
            elif name == "Events":
                self.events_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_events_analysis)
            elif name == "AUTOTUNE":
                self.autotune_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_autotune_analysis)
            elif name == "TAKEOFF":
                self.takeoff_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_takeoff_analysis)
            else:
                self.stall_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_stall_analysis)
            action_layout.addWidget(analyse_button)
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
        elif name == "Landing":
            return (
                "Landing\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing Landing evidence pipeline."
            )
        elif name == "Events":
            return (
                "Events\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing Event Timeline evidence pipeline."
            )
        elif name == "AUTOTUNE":
            return (
                "AUTOTUNE\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing AUTOTUNE evidence pipeline."
            )
        elif name == "TAKEOFF":
            return (
                "TAKEOFF\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing TAKEOFF evidence pipeline."
            )
        elif name == "Stall":
            return (
                "Stall\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing Stall evidence pipeline."
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

    def _selection_error(self, analysis: str) -> str | None:
        if self._selected_log is None:
            return f"Select a BIN log before running {analysis} analysis."
        if self._selected_log.suffix.lower() != ".bin":
            return f"The selected {analysis} source must have a .bin extension."
        if not self._selected_log.is_file():
            return f"The selected BIN log does not exist: {self._selected_log}"
        return None

    def _update_analysis_controls(self) -> None:
        busy = self._analysis_thread is not None
        for analysis, button in (
            ("Landing", self.landing_analyse_button),
            ("Events", self.events_analyse_button),
            ("TAKEOFF", self.takeoff_analyse_button),
            ("AUTOTUNE", self.autotune_analyse_button),
            ("Stall", self.stall_analyse_button),
        ):
            if button is not None:
                valid = self._selection_error(analysis) is None
                button.setEnabled(
                    not busy and valid and not self._close_after_worker
                )
        self.choose_log_button.setEnabled(not busy and not self._close_after_worker)

    def _set_analysis_busy(self, busy: bool) -> None:
        for analysis, button in (
            ("Landing", self.landing_analyse_button),
            ("Events", self.events_analyse_button),
            ("TAKEOFF", self.takeoff_analyse_button),
            ("AUTOTUNE", self.autotune_analyse_button),
            ("Stall", self.stall_analyse_button),
        ):
            if button is not None:
                is_active = busy and analysis == self._active_analysis
                button.setText("Analysing…" if is_active else "Analyse")
        self._update_analysis_controls()

    @Slot(str)
    def _analysis_succeeded(self, report: str) -> None:
        assert self._active_analysis is not None
        self.report_for(self._active_analysis).setPlainText(report)
        self.statusBar().showMessage(f"{self._active_analysis} analysis complete")

    @Slot(object)
    def _analysis_failed(self, exc: Exception) -> None:
        assert self._active_analysis is not None
        if isinstance(exc, UnsupportedFirmwareError):
            message = f"Unsupported firmware.\n{exc}"
        elif isinstance(exc, OSError):
            message = f"Unable to read log: {exc}"
        else:
            message = (
                f"{self._active_analysis} analysis failed unexpectedly: {exc}"
            )
        self._show_analysis_error(self._active_analysis, message)

    def _show_analysis_error(self, analysis: str, message: str) -> None:
        heading = f"{analysis} Analysis Error"
        self.report_for(analysis).setPlainText(
            f"{heading}\n"
            f"{'=' * len(heading)}\n"
            f"{message}"
        )
        self.statusBar().showMessage(message.replace("\n", " — "))

    @Slot()
    def _analysis_thread_finished(self) -> None:
        self._analysis_thread = None
        self._analysis_worker = None
        self._active_analysis = None
        self._set_analysis_busy(False)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _update_status(self, action: str | None = None) -> None:
        source = str(self._selected_log) if self._selected_log else "no BIN selected"
        if self._analysis_thread is not None:
            self.statusBar().showMessage(
                f"{self._active_analysis} analysis running — {source}"
            )
            return
        prefix = f"{action} — " if action else ""
        if self.current_analysis == "Overview":
            self.statusBar().showMessage(
                f"{prefix}Overview — {source} — choose a module"
            )
            return
        state = (
            "ready"
            if self.current_analysis in _CONNECTED_ANALYSES
            else "analysis not connected"
        )
        self.statusBar().showMessage(
            f"{prefix}{self.current_analysis} — {source} — {state}"
        )

    def closeEvent(self, event) -> None:
        """Defer destruction until an active analysis worker has exited."""
        if self._analysis_thread is not None:
            self._close_after_worker = True
            self.choose_log_button.setEnabled(False)
            self._update_analysis_controls()
            self.statusBar().showMessage(
                f"Waiting for {self._active_analysis} analysis to finish before closing"
            )
            event.ignore()
            return
        documentation_windows = tuple(self._docs_windows.values())
        self._docs_windows.clear()
        for window in documentation_windows:
            window.close()
        event.accept()
