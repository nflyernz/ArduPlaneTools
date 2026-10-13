"""Phase 1 Qt Widgets shell for ArduPlaneTools."""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCommandLinkButton,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.log_reader import UnsupportedFirmwareError
from core.battery_pack_store import LogPackState

from .autotune_adapter import analyse_autotune_log
from .battery_adapter import analyse_battery_log
from .docs_viewer import ModuleDocsWindow
from .events_adapter import analyse_events_log
from .landing_adapter import analyse_landing_log
from .pack_management_adapter import (
    BatteryPackManagementService,
    PackManagementResult,
    PackManagementState,
)
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
    (
        "Landing",
        "Events",
        "Battery",
        "Battery Pack Management",
        "AUTOTUNE",
        "TAKEOFF",
        "Stall",
    )
)

_EXECUTABLE_ANALYSES = _CONNECTED_ANALYSES - {"Battery Pack Management"}


class _AnalysisWorker(QObject):
    """Run one analysis adapter call away from the GUI thread."""

    succeeded = Signal(object)
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
        battery_adapter=analyse_battery_log,
        pack_management_service=None,
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
        self._battery_adapter = battery_adapter
        self._pack_management_service = (
            pack_management_service or BatteryPackManagementService()
        )
        self._pack_management_state: PackManagementState | None = None
        self._pack_management_task: str | None = None
        self._pending_pack_lookup: Path | None = None
        self._analysis_thread: QThread | None = None
        self._analysis_worker: _AnalysisWorker | None = None
        self._active_analysis: str | None = None
        self._close_after_worker = False
        self.autotune_analyse_button: QPushButton | None = None
        self.takeoff_analyse_button: QPushButton | None = None
        self.stall_analyse_button: QPushButton | None = None
        self.landing_analyse_button: QPushButton | None = None
        self.events_analyse_button: QPushButton | None = None
        self.battery_analyse_button: QPushButton | None = None
        self.battery_read_only_notice: QLabel | None = None
        self.pack_selected_bin_value: QLabel | None = None
        self.pack_association_value: QLabel | None = None
        self.pack_assign_combo: QComboBox | None = None
        self.pack_assign_button: QPushButton | None = None
        self.pack_create_edit: QLineEdit | None = None
        self.pack_create_button: QPushButton | None = None
        self.pack_rename_combo: QComboBox | None = None
        self.pack_rename_edit: QLineEdit | None = None
        self.pack_rename_button: QPushButton | None = None
        self.pack_record_history_button: QPushButton | None = None

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
        self._pack_management_state = None
        self._pending_pack_lookup = None
        displayed = str(selected)
        self.source_path_edit.setText(displayed)
        self.source_path_edit.setToolTip(displayed)
        self.source_path_edit.setCursorPosition(0)
        self._update_analysis_controls()
        self._update_status("BIN selected")
        self._refresh_pack_management_view("Association not loaded.")
        if self.current_analysis == "Battery Pack Management":
            self._request_pack_lookup()

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

    def start_battery_analysis(self) -> None:
        """Start read-only Battery Analysis through the shared worker."""
        self._start_analysis("Battery", self._battery_adapter)

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
        self._start_worker(analysis, path, adapter)

    def _start_worker(self, analysis: str, path: Path, adapter) -> None:
        """Start one adapter using the shared GUI worker lifecycle."""
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

        if name in _EXECUTABLE_ANALYSES:
            analyse_button = QPushButton("Analyse")
            analyse_button.setObjectName(f"{name.lower()}AnalyseButton")
            if name == "Landing":
                self.landing_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_landing_analysis)
            elif name == "Events":
                self.events_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_events_analysis)
            elif name == "Battery":
                self.battery_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_battery_analysis)
            elif name == "AUTOTUNE":
                self.autotune_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_autotune_analysis)
            elif name == "TAKEOFF":
                self.takeoff_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_takeoff_analysis)
            elif name == "Stall":
                self.stall_analyse_button = analyse_button
                analyse_button.clicked.connect(self.start_stall_analysis)
            action_layout.addWidget(analyse_button)
        layout.addLayout(action_layout)

        if name == "Battery":
            self.battery_read_only_notice = QLabel(
                "<b>Read-only Battery Analysis</b><br>"
                "Analyses the selected BIN without changing Pack IDs, log "
                "associations or battery history. Use the Battery Pack "
                "Management tab for tracking and explicit history recording."
            )
            self.battery_read_only_notice.setWordWrap(True)
            layout.addWidget(self.battery_read_only_notice)

        if name == "Battery Pack Management":
            self._create_pack_management_controls(layout)

        report = QPlainTextEdit()
        report.setObjectName(f"{name.lower().replace(' ', '_')}_report")
        report.setReadOnly(True)
        report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        report.setPlainText(self._context_message(name))
        report.setToolTip("Analysis report area")
        layout.addWidget(report, 1)
        self._reports[name] = report
        return page

    def _create_pack_management_controls(self, layout: QVBoxLayout) -> None:
        """Build explicit pack identity and history controls."""
        source_group = QGroupBox("Selected BIN")
        source_form = QFormLayout(source_group)
        self.pack_selected_bin_value = QLabel("No BIN selected")
        self.pack_selected_bin_value.setWordWrap(True)
        self.pack_association_value = QLabel("Unseen")
        source_form.addRow("Source:", self.pack_selected_bin_value)
        source_form.addRow("Association:", self.pack_association_value)
        source_form.addRow(
            "Scope:",
            QLabel("The association applies to the entire source BIN."),
        )
        layout.addWidget(source_group)

        assignment_group = QGroupBox("Assign existing Pack ID")
        assignment_layout = QHBoxLayout(assignment_group)
        self.pack_assign_combo = QComboBox()
        self.pack_assign_button = QPushButton("Assign selected BIN")
        self.pack_assign_button.clicked.connect(self.assign_existing_pack)
        assignment_layout.addWidget(self.pack_assign_combo, 1)
        assignment_layout.addWidget(self.pack_assign_button)
        layout.addWidget(assignment_group)

        create_group = QGroupBox("Create and assign Pack ID")
        create_layout = QHBoxLayout(create_group)
        self.pack_create_edit = QLineEdit()
        self.pack_create_edit.setPlaceholderText("New Pack ID")
        self.pack_create_edit.textChanged.connect(self._update_analysis_controls)
        self.pack_create_button = QPushButton("Create and assign")
        self.pack_create_button.clicked.connect(self.create_and_assign_pack)
        create_layout.addWidget(self.pack_create_edit, 1)
        create_layout.addWidget(self.pack_create_button)
        layout.addWidget(create_group)

        rename_group = QGroupBox("Rename existing Pack ID")
        rename_form = QFormLayout(rename_group)
        self.pack_rename_combo = QComboBox()
        self.pack_rename_edit = QLineEdit()
        self.pack_rename_edit.setPlaceholderText("Replacement Pack ID")
        self.pack_rename_edit.textChanged.connect(self._update_analysis_controls)
        self.pack_rename_button = QPushButton("Rename globally")
        self.pack_rename_button.clicked.connect(self.rename_pack)
        rename_form.addRow("Existing:", self.pack_rename_combo)
        rename_form.addRow("Replacement:", self.pack_rename_edit)
        rename_form.addRow(
            "Effect:",
            QLabel("Updates every associated BIN identity using this Pack ID."),
        )
        rename_form.addRow(self.pack_rename_button)
        layout.addWidget(rename_group)

        history_group = QGroupBox("Record AUTO takeoff history")
        history_layout = QHBoxLayout(history_group)
        history_layout.addWidget(
            QLabel("Explicitly record supported AUTO takeoff evidence from this BIN."),
            1,
        )
        self.pack_record_history_button = QPushButton("Record history")
        self.pack_record_history_button.clicked.connect(self.record_pack_history)
        history_layout.addWidget(self.pack_record_history_button)
        layout.addWidget(history_group)

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
        elif name == "Battery":
            return (
                "Battery\n\n"
                "Select a BIN log above, then choose Analyse.\n\n"
                "Reports use the existing Battery evidence pipeline without "
                "changing pack tracking or history."
            )
        elif name == "Battery Pack Management":
            return (
                "Battery Pack Management\n\n"
                "Select a BIN log to load its persistent association. Changes "
                "and history recording occur only after explicit confirmation."
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

    def _request_pack_lookup(self) -> None:
        """Resolve the current BIN association without writing persistence."""
        if self._selected_log is None:
            self._pack_management_state = None
            self._refresh_pack_management_view("Select a BIN log to begin.")
            return
        if self._analysis_thread is not None:
            self._pending_pack_lookup = self._selected_log
            self._refresh_pack_management_view("Association lookup pending.")
            return
        path = self._selected_log
        self._pack_management_task = "lookup"
        self._refresh_pack_management_view("Identifying source BIN…")
        self._start_worker(
            "Battery Pack Management",
            path,
            self._pack_management_service.lookup,
        )

    def assign_existing_pack(self) -> None:
        """Confirm and assign the selected BIN to a known Pack ID."""
        state = self._current_pack_state()
        if state is None or self.pack_assign_combo is None:
            return
        pack_id = self.pack_assign_combo.currentText()
        if (
            state.association.state is LogPackState.TRACKED
            and state.association.pack_id == pack_id
        ):
            self._show_pack_message(f"Pack assignment is already {pack_id}.")
            return
        if not self._confirm_pack_action(
            "Assign Battery Pack",
            f"Source BIN: {state.log_path.name}\n"
            f"Current association: {self._association_text(state)}\n"
            f"Proposed Pack ID: {pack_id}\n\n"
            "Apply this association to the entire source BIN?",
        ):
            return
        self._start_pack_mutation(
            "assign",
            state,
            lambda _path: self._pack_management_service.assign_existing(
                state,
                pack_id,
            ),
        )

    def create_and_assign_pack(self) -> None:
        """Confirm atomic Pack ID creation and source assignment."""
        state = self._current_pack_state()
        if state is None or self.pack_create_edit is None:
            return
        pack_id = self.pack_create_edit.text().strip()
        if not pack_id:
            self._show_pack_message("Enter a new Pack ID.", error=True)
            return
        if not self._confirm_pack_action(
            "Create Battery Pack",
            f"Source BIN: {state.log_path.name}\n"
            f"Current association: {self._association_text(state)}\n"
            f"New Pack ID: {pack_id}\n\n"
            "Create this Pack ID and associate the entire source BIN?",
        ):
            return
        self._start_pack_mutation(
            "create",
            state,
            lambda _path: self._pack_management_service.create_and_assign(
                state,
                pack_id,
            ),
        )

    def rename_pack(self) -> None:
        """Confirm a global Pack ID rename."""
        state = self._current_pack_state()
        if (
            state is None
            or self.pack_rename_combo is None
            or self.pack_rename_edit is None
        ):
            return
        old_id = self.pack_rename_combo.currentText()
        new_id = self.pack_rename_edit.text().strip()
        if not new_id:
            self._show_pack_message("Enter a replacement Pack ID.", error=True)
            return
        if old_id == new_id:
            self._show_pack_message("Pack ID is unchanged.")
            return
        if not self._confirm_pack_action(
            "Rename Battery Pack",
            f"Rename Pack ID {old_id} to {new_id}?\n\n"
            "This updates every associated BIN identity, not only the selected BIN.",
        ):
            return
        self._start_pack_mutation(
            "rename",
            state,
            lambda _path: self._pack_management_service.rename(
                state,
                old_id,
                new_id,
            ),
        )

    def record_pack_history(self) -> None:
        """Confirm explicit whole-BIN AUTO takeoff history recording."""
        state = self._current_pack_state()
        if (
            state is None
            or state.association.state is not LogPackState.TRACKED
            or state.association.pack_id is None
        ):
            return
        if not self._confirm_pack_action(
            "Record Battery History",
            f"Source BIN: {state.log_path.name}\n"
            f"Tracked Pack ID: {state.association.pack_id}\n\n"
            "Record all supported AUTO takeoff observations from this BIN?",
        ):
            return
        self._start_pack_mutation(
            "history",
            state,
            lambda _path: self._pack_management_service.record_history(state),
        )

    def _start_pack_mutation(self, task: str, state, adapter) -> None:
        if self._analysis_thread is not None:
            return
        self._pack_management_task = task
        self._show_pack_message("Operation in progress…")
        self._start_worker("Battery Pack Management", state.log_path, adapter)

    def _current_pack_state(self) -> PackManagementState | None:
        state = self._pack_management_state
        if (
            state is None
            or self._selected_log is None
            or state.log_path != self._selected_log
            or self._analysis_thread is not None
        ):
            return None
        return state

    @staticmethod
    def _association_text(state: PackManagementState) -> str:
        if state.association.state is LogPackState.TRACKED:
            return f"Tracked — {state.association.pack_id}"
        if state.association.state is LogPackState.NOT_TRACKED:
            return "Not tracked"
        return "Unseen"

    def _refresh_pack_management_view(
        self,
        message: str | None = None,
        selected_pack_id: str | None = None,
    ) -> None:
        """Render selected source and the latest persisted read-only state."""
        if self.pack_selected_bin_value is None:
            return
        if self._selected_log is None:
            self.pack_selected_bin_value.setText("No BIN selected")
            self.pack_association_value.setText("Unseen")
            pack_ids = ()
        else:
            self.pack_selected_bin_value.setText(self._selected_log.name)
            state = self._pack_management_state
            if state is not None and state.log_path == self._selected_log:
                self.pack_association_value.setText(self._association_text(state))
                pack_ids = state.pack_ids
            else:
                self.pack_association_value.setText("Pending lookup")
                pack_ids = ()

        for combo in (self.pack_assign_combo, self.pack_rename_combo):
            if combo is not None:
                current = selected_pack_id or combo.currentText()
                combo.clear()
                combo.addItems(pack_ids)
                index = combo.findText(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
        if message is not None:
            self.report_for("Battery Pack Management").setPlainText(message)
        self._update_analysis_controls()

    def _show_pack_message(self, message: str, *, error: bool = False) -> None:
        heading = "Battery Pack Management Error" if error else "Battery Pack Management"
        self.report_for("Battery Pack Management").setPlainText(
            f"{heading}\n{'=' * len(heading)}\n{message}"
        )
        self.statusBar().showMessage(message)

    def _confirm_pack_action(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _on_tab_changed(self, _index: int) -> None:
        self._update_status()
        if self.current_analysis == "Battery Pack Management":
            state = self._pack_management_state
            if (
                self._selected_log is not None
                and (state is None or state.log_path != self._selected_log)
            ):
                self._request_pack_lookup()

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
            ("Battery", self.battery_analyse_button),
            ("TAKEOFF", self.takeoff_analyse_button),
            ("AUTOTUNE", self.autotune_analyse_button),
            ("Stall", self.stall_analyse_button),
        ):
            if button is not None:
                valid = self._selection_error(analysis) is None
                button.setEnabled(
                    not busy and valid and not self._close_after_worker
                )
        pack_ready = (
            not busy
            and not self._close_after_worker
            and self._current_pack_state() is not None
        )
        pack_ids = (
            self._pack_management_state.pack_ids
            if self._pack_management_state is not None
            else ()
        )
        if self.pack_assign_button is not None:
            self.pack_assign_button.setEnabled(pack_ready and bool(pack_ids))
        if self.pack_create_button is not None:
            self.pack_create_button.setEnabled(
                pack_ready
                and self.pack_create_edit is not None
                and bool(self.pack_create_edit.text().strip())
            )
        if self.pack_rename_button is not None:
            self.pack_rename_button.setEnabled(
                pack_ready
                and bool(pack_ids)
                and self.pack_rename_edit is not None
                and bool(self.pack_rename_edit.text().strip())
            )
        if self.pack_record_history_button is not None:
            association = (
                self._pack_management_state.association
                if self._pack_management_state is not None
                else None
            )
            self.pack_record_history_button.setEnabled(
                pack_ready
                and association is not None
                and association.state is LogPackState.TRACKED
            )
        self.choose_log_button.setEnabled(not busy and not self._close_after_worker)

    def _set_analysis_busy(self, busy: bool) -> None:
        for analysis, button in (
            ("Landing", self.landing_analyse_button),
            ("Events", self.events_analyse_button),
            ("Battery", self.battery_analyse_button),
            ("TAKEOFF", self.takeoff_analyse_button),
            ("AUTOTUNE", self.autotune_analyse_button),
            ("Stall", self.stall_analyse_button),
        ):
            if button is not None:
                is_active = busy and analysis == self._active_analysis
                button.setText("Analysing…" if is_active else "Analyse")
        self._update_analysis_controls()

    @Slot(object)
    def _analysis_succeeded(self, report: object) -> None:
        assert self._active_analysis is not None
        if self._active_analysis == "Battery Pack Management":
            self._pack_management_succeeded(report)
            return
        assert isinstance(report, str)
        self.report_for(self._active_analysis).setPlainText(report)
        self.statusBar().showMessage(f"{self._active_analysis} analysis complete")

    @Slot(object)
    def _analysis_failed(self, exc: Exception) -> None:
        assert self._active_analysis is not None
        if self._active_analysis == "Battery Pack Management":
            self._show_pack_message(str(exc), error=True)
            return
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
        finished_analysis = self._active_analysis
        self._analysis_thread = None
        self._analysis_worker = None
        self._active_analysis = None
        self._pack_management_task = None
        self._set_analysis_busy(False)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()
            return
        if finished_analysis == "Battery Pack Management":
            pending = self._pending_pack_lookup
            self._pending_pack_lookup = None
            if pending is not None and pending == self._selected_log:
                self._request_pack_lookup()

    def _pack_management_succeeded(self, result: object) -> None:
        if isinstance(result, PackManagementResult):
            state = result.state
            message = result.message
            selected_pack_id = result.selected_pack_id
            if self.pack_create_edit is not None and result.changed:
                self.pack_create_edit.clear()
            if self.pack_rename_edit is not None and result.changed:
                self.pack_rename_edit.clear()
        elif isinstance(result, PackManagementState):
            state = result
            message = "Persistent association loaded."
            selected_pack_id = None
        else:
            self._show_pack_message(
                "Management operation returned an unexpected result.",
                error=True,
            )
            return

        if self._selected_log == state.log_path:
            self._pack_management_state = state
            self._refresh_pack_management_view(message, selected_pack_id)
            self.statusBar().showMessage(message)
        elif self._selected_log is not None:
            self._pending_pack_lookup = self._selected_log

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
