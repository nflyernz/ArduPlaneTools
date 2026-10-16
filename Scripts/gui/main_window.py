"""Phase 1 Qt Widgets shell for ArduPlaneTools."""

from pathlib import Path

from PySide6.QtCore import QThread, Slot
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

from .analysis_worker import AnalysisWorker
from .autotune_adapter import analyse_autotune_log
from .battery_adapter import analyse_battery_log
from .docs_viewer import DocumentationController
from .events_adapter import analyse_events_log
from .landing_adapter import analyse_landing_log
from .module_catalog import (
    EXECUTABLE_ANALYSES as _EXECUTABLE_ANALYSES,
    MODULE_DESCRIPTIONS as _MODULE_DESCRIPTIONS,
    OVERVIEW_SECTIONS as _OVERVIEW_SECTIONS,
    PACK_ID_PLACEHOLDER as _PACK_ID_PLACEHOLDER,
    connection_status,
    display_label,
)
from .pack_management_adapter import (
    BatteryPackManagementService,
    PackManagementResult,
    PackManagementState,
)
from .pack_performance_widget import PackPerformanceController
from .radio_link_adapter import analyse_radio_link_log
from .radio_link_widget import RadioLinkController
from .range_walk_controller import RangeWalkPreviewController
from .stall_adapter import analyse_stall_log
from .takeoff_adapter import analyse_takeoff_log


ANALYSIS_TABS = (
    "Battery",
    "Battery Pack Management",
    "Pack Performance",
    "TAKEOFF",
    "Landing",
    "AUTOTUNE",
    "Stall",
    "Events",
    "Radio Link",
    "Range-Walk Comparison",
)


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
        pack_performance_service=None,
        radio_link_adapter=analyse_radio_link_log,
        radio_link_csv_service=None,
        range_walk_adapter=None,
        range_walk_inspection_adapter=None,
        range_walk_history_service=None,
    ):
        super().__init__()
        self._selected_log: Path | None = None
        self._reports: dict[str, QPlainTextEdit] = {}
        self.overview_buttons: dict[str, QCommandLinkButton] = {}
        self._documentation = DocumentationController(self)
        self.docs_buttons = self._documentation.docs_buttons
        self.procedure_buttons = self._documentation.procedure_buttons
        self._docs_windows = self._documentation.docs_windows
        self._procedure_windows = self._documentation.procedure_windows
        self._autotune_adapter = autotune_adapter
        self._takeoff_adapter = takeoff_adapter
        self._stall_adapter = stall_adapter
        self._landing_adapter = landing_adapter
        self._events_adapter = events_adapter
        self._battery_adapter = battery_adapter
        self._pack_management_service = (
            pack_management_service or BatteryPackManagementService()
        )
        self._pack_performance = PackPerformanceController(
            pack_performance_service,
            self._start_worker,
            lambda: self._analysis_thread is not None,
            self.statusBar().showMessage,
        )
        self._radio_link = RadioLinkController(
            radio_link_adapter,
            radio_link_csv_service,
            self._start_worker,
            lambda: self._selected_log,
            lambda: self._selection_error("Radio Link"),
            lambda: self._analysis_thread is not None,
            self._show_analysis_error,
            self.statusBar().showMessage,
        )
        self._range_walk = RangeWalkPreviewController(
            range_walk_adapter, range_walk_inspection_adapter,
            range_walk_history_service, self._start_worker,
            lambda: self._analysis_thread is not None,
            self.statusBar().showMessage,
        )
        self._pack_management_state: PackManagementState | None = None
        self._pack_management_task: str | None = None
        self._pending_pack_lookup: Path | None = None
        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._active_analysis: str | None = None
        self._close_after_worker = False
        self.autotune_analyse_button: QPushButton | None = None
        self.takeoff_analyse_button: QPushButton | None = None
        self.stall_analyse_button: QPushButton | None = None
        self.landing_analyse_button: QPushButton | None = None
        self.events_analyse_button: QPushButton | None = None
        self.battery_analyse_button: QPushButton | None = None
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
            self.analysis_tabs.addTab(
                self._create_analysis_page(name),
                display_label(name),
            )
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
    def _autotune_worker(self) -> AnalysisWorker | None:
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
        """Return the stable identifier for the visible analysis context."""
        index = self.analysis_tabs.currentIndex()
        return "Overview" if index <= 0 else ANALYSIS_TABS[index - 1]

    def report_for(self, analysis: str) -> QPlainTextEdit:
        """Return the read-only report surface for an analysis tab."""
        return self._reports[analysis]

    def show_analysis_tab(self, analysis: str) -> None:
        """Navigate from Overview to an existing analysis tab."""
        self.analysis_tabs.setCurrentIndex(ANALYSIS_TABS.index(analysis) + 1)

    def open_module_docs(self, module: str) -> None:
        """Open or focus the retained documentation window for one module."""
        self._documentation.open_docs(module)

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
        self._radio_link.source_changed(selected)
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
        worker = AnalysisWorker(path, adapter)
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

        for section_title, module_names in _OVERVIEW_SECTIONS:
            section = QGroupBox()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(8, 6, 8, 8)
            section_layout.setSpacing(2)
            section_heading = QLabel(section_title)
            section_heading.setObjectName("overviewSectionHeading")
            section_heading_font = section_heading.font()
            section_heading_font.setBold(True)
            section_heading.setFont(section_heading_font)
            section_layout.addWidget(section_heading)
            modules = QGridLayout()
            modules.setContentsMargins(0, 0, 0, 0)
            modules.setHorizontalSpacing(10)
            modules.setVerticalSpacing(4)
            modules.setColumnStretch(0, 1)
            modules.setColumnStretch(1, 1)
            for index, name in enumerate(module_names):
                button = QCommandLinkButton(
                    display_label(name),
                    _MODULE_DESCRIPTIONS[name],
                )
                button.setObjectName(
                    f"overview_{name.lower().replace(' ', '_').replace('-', '_')}"
                )
                button_font = button.font()
                button_font.setPointSizeF(button_font.pointSizeF() + 2.0)
                button.setFont(button_font)
                button.setMinimumHeight(70)
                button.clicked.connect(
                    lambda _checked=False, analysis=name: self.show_analysis_tab(
                        analysis
                    )
                )
                modules.addWidget(button, index // 2, index % 2)
                self.overview_buttons[name] = button
            section_layout.addLayout(modules)
            layout.addWidget(section)
        layout.addStretch(1)
        return page

    def _create_analysis_page(self, name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        self._add_module_header(name, layout)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self._documentation.add_buttons(name, action_layout)

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

        if name == "Battery Pack Management":
            self._create_pack_management_controls(layout)

        if name == "Pack Performance":
            widget = self._pack_performance.create_widget(page)
            layout.addWidget(widget, 1)
            self._reports[name] = widget.report
            return page

        if name == "Radio Link":
            widget = self._radio_link.create_widget(page)
            layout.addWidget(widget, 1)
            self._reports[name] = widget.report
            return page

        if name == "Range-Walk Comparison":
            widget = self._range_walk.create_widget(page)
            layout.addWidget(widget, 1)
            self._reports[name] = widget.report
            return page

        report = QPlainTextEdit()
        report.setObjectName(f"{name.lower().replace(' ', '_')}_report")
        report.setReadOnly(True)
        report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        report.setPlainText(
            "No management operation run yet."
            if name == "Battery Pack Management"
            else "No analysis run yet."
        )
        report.setToolTip("Analysis report area")
        layout.addWidget(report, 1)
        self._reports[name] = report
        return page

    def _add_module_header(self, name: str, layout: QVBoxLayout) -> None:
        """Add the shared name, purpose and first action for one module."""
        slug = name.lower().replace(" ", "_").replace("-", "_")
        heading = QLabel(display_label(name))
        heading.setObjectName(f"{slug}HeaderTitle")
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)

        description = QLabel(_MODULE_DESCRIPTIONS[name])
        description.setObjectName(f"{slug}HeaderDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        instruction = QLabel(self._module_instruction(name))
        instruction.setObjectName(f"{slug}HeaderInstruction")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        if name == "Battery":
            read_only = QLabel(
                "This analysis is read-only. Battery pack identities, log "
                "associations and history are managed separately under Battery "
                "Pack Management."
            )
            read_only.setObjectName("batteryOperationalNote")
            read_only.setWordWrap(True)
            layout.addWidget(read_only)

    @staticmethod
    def _module_instruction(name: str) -> str:
        if name == "Battery Pack Management":
            return "Select a BIN log above to view or manage its pack association."
        if name == "Pack Performance":
            return (
                "Select a Pack ID, then choose View report. "
                "No BIN selection is required."
            )
        if name == "Range-Walk Comparison":
            return (
                "Select an EdgeTX CSV to detect markers and prepare a range walk. "
                "The shared Source BIN selection does not apply."
            )
        return "Select a BIN log above, then choose Analyse."

    def _create_pack_management_controls(self, layout: QVBoxLayout) -> None:
        """Build explicit pack identity and history controls."""
        source_group = QGroupBox("Selected BIN")
        source_form = QFormLayout(source_group)
        self.pack_selected_bin_value = QLabel("No BIN selected")
        self.pack_selected_bin_value.setWordWrap(True)
        self.pack_association_value = QLabel("Unseen")
        source_form.addRow("Source:", self.pack_selected_bin_value)
        source_form.addRow("Association:", self.pack_association_value)
        source_form.addRow(QLabel("Pack associations apply to the entire BIN log."))
        layout.addWidget(source_group)

        assignment_group = QGroupBox("Assign existing Pack ID")
        assignment_layout = QHBoxLayout(assignment_group)
        self.pack_assign_combo = QComboBox()
        self.pack_assign_combo.addItem(_PACK_ID_PLACEHOLDER, None)
        self.pack_assign_combo.currentIndexChanged.connect(
            self._update_analysis_controls
        )
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
        self.pack_rename_combo.addItem(_PACK_ID_PLACEHOLDER, None)
        self.pack_rename_combo.currentIndexChanged.connect(
            self._update_analysis_controls
        )
        self.pack_rename_edit = QLineEdit()
        self.pack_rename_edit.setPlaceholderText("Replacement Pack ID")
        self.pack_rename_edit.textChanged.connect(self._update_analysis_controls)
        self.pack_rename_button = QPushButton("Rename globally")
        self.pack_rename_button.clicked.connect(self.rename_pack)
        rename_form.addRow("Existing:", self.pack_rename_combo)
        rename_form.addRow("Replacement:", self.pack_rename_edit)
        rename_form.addRow(
            "Effect:",
            QLabel(
                "Updates the Pack ID in every saved BIN association that uses it."
            ),
        )
        rename_form.addRow(self.pack_rename_button)
        layout.addWidget(rename_group)

        history_group = QGroupBox("Record AUTO takeoff history")
        history_layout = QHBoxLayout(history_group)
        history_layout.addWidget(
            QLabel(
                "<b>Effect:</b> Adds supported AUTO takeoff data from this BIN "
                "to the assigned pack's history."
            ),
            1,
        )
        self.pack_record_history_button = QPushButton("Record history")
        self.pack_record_history_button.clicked.connect(self.record_pack_history)
        history_layout.addWidget(self.pack_record_history_button)
        layout.addWidget(history_group)

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
        pack_id = self.pack_assign_combo.currentData()
        if not isinstance(pack_id, str):
            return
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
        old_id = self.pack_rename_combo.currentData()
        if not isinstance(old_id, str):
            return
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
                current = selected_pack_id or combo.currentData()
                combo.clear()
                combo.addItem(_PACK_ID_PLACEHOLDER, None)
                for pack_id in pack_ids:
                    combo.addItem(pack_id, pack_id)
                index = combo.findData(current)
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
        elif self.current_analysis == "Pack Performance":
            self._pack_performance.request_refresh()

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
            selected = (
                self.pack_assign_combo.currentData()
                if self.pack_assign_combo is not None
                else None
            )
            self.pack_assign_button.setEnabled(pack_ready and selected in pack_ids)
        if self.pack_create_button is not None:
            self.pack_create_button.setEnabled(
                pack_ready
                and self.pack_create_edit is not None
                and bool(self.pack_create_edit.text().strip())
            )
        if self.pack_rename_button is not None:
            selected = (
                self.pack_rename_combo.currentData()
                if self.pack_rename_combo is not None
                else None
            )
            self.pack_rename_button.setEnabled(
                pack_ready
                and selected in pack_ids
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
        self._pack_performance.set_busy(busy or self._close_after_worker)
        self._radio_link.set_busy(busy or self._close_after_worker)
        self._range_walk.set_busy(busy or self._close_after_worker)

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
        if self._active_analysis == "Pack Performance":
            assert self._pack_performance.handle_success(report)
            return
        if self._active_analysis == "Radio Link":
            assert self._radio_link.handle_success(report)
            return
        if self._active_analysis == "Range-Walk Comparison":
            assert self._range_walk.handle_success(report)
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
        if self._active_analysis == "Pack Performance":
            self._pack_performance.handle_failure(exc)
            return
        if self._active_analysis == "Radio Link":
            self._radio_link.handle_failure(exc)
            return
        if self._active_analysis == "Range-Walk Comparison":
            self._range_walk.handle_failure(exc)
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
        self._pack_performance.worker_finished(
            finished_analysis == "Pack Performance"
        )
        self._range_walk.worker_finished(
            finished_analysis == "Range-Walk Comparison"
        )
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
        state = connection_status(self.current_analysis)
        self.statusBar().showMessage(
            f"{prefix}{display_label(self.current_analysis)} — {source} — {state}"
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
        self._documentation.close_all()
        event.accept()
