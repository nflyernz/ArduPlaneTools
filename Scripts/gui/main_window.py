"""Phase 1 Qt Widgets shell for ArduPlaneTools."""

from pathlib import Path

from core.battery_pack_store import LogPackState
from core.log_reader import UnsupportedFirmwareError
from PySide6.QtCore import QSettings, QSize, Qt, QThread, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCommandLinkButton,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .analysis_worker import AnalysisWorker
from .autotune_adapter import analyse_autotune_log
from .battery_adapter import analyse_battery_log
from .docs_viewer import DocumentationController
from .events_adapter import analyse_events_log
from .landing_adapter import analyse_landing_log
from .log_dialog_settings import remember_directory, starting_directory
from .module_catalog import (
    EXECUTABLE_ANALYSES as _EXECUTABLE_ANALYSES,
)
from .module_catalog import (
    MODULE_DESCRIPTIONS as _MODULE_DESCRIPTIONS,
)
from .module_catalog import (
    OVERVIEW_SECTIONS as _OVERVIEW_SECTIONS,
)
from .module_catalog import (
    PACK_ID_PLACEHOLDER as _PACK_ID_PLACEHOLDER,
)
from .module_catalog import (
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

WINDOW_SIZE_KEY = "main_window/size"


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
        self._pending_pack_lookup_requested = False
        self._pack_delete_preview = None
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
        self.pack_archive_combo: QComboBox | None = None
        self.pack_restore_combo: QComboBox | None = None
        self.pack_delete_combo: QComboBox | None = None
        self.pack_archive_button: QPushButton | None = None
        self.pack_restore_button: QPushButton | None = None
        self.pack_delete_button: QPushButton | None = None
        self.pack_delete_preview_text: QPlainTextEdit | None = None
        self.pack_record_history_button: QPushButton | None = None
        self.pack_controls_scroll: QScrollArea | None = None

        self.setWindowTitle("ArduPlaneTools")
        self._restore_window_size()

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

    @staticmethod
    def _screen_available_size() -> QSize:
        """Return the primary screen's usable size before the window is shown."""
        screen = QApplication.primaryScreen()
        return screen.availableGeometry().size() if screen else QSize(1200, 930)

    def _restore_window_size(self) -> None:
        """Use a taller first-run size and keep saved dimensions on screen."""
        available = self._screen_available_size()
        self.setMinimumSize(min(900, available.width()), min(600, available.height()))
        saved = QSettings("ArduPlaneTools", "ArduPlaneTools").value(WINDOW_SIZE_KEY)
        preferred = saved if isinstance(saved, QSize) and saved.isValid() else QSize(1200, 930)
        self.resize(
            min(preferred.width(), available.width()),
            min(preferred.height(), available.height()),
        )

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
            str(starting_directory()),
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

        remember_directory(selected_log)
        self.set_selected_log(selected_log)

    def set_selected_log(self, path: Path) -> None:
        """Update shared source state and its full-path presentation."""
        selected = path.expanduser().resolve()
        self._selected_log = selected
        self._pack_management_state = None
        self._pending_pack_lookup = None
        self._pending_pack_lookup_requested = False
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

    def _start_worker(self, analysis: str, path: Path | None, adapter) -> None:
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
            controls_scroll = QScrollArea(page)
            controls_scroll.setWidgetResizable(True)
            controls_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            controls_scroll.setMinimumHeight(280)
            controls_content = QWidget()
            controls_layout = QVBoxLayout(controls_content)
            controls_layout.setContentsMargins(0, 0, 0, 0)
            controls_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            self._create_pack_management_controls(controls_layout)
            controls_scroll.setWidget(controls_content)
            self.pack_controls_scroll = controls_scroll
            layout.addWidget(controls_scroll, 1)

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
        if name == "Battery Pack Management":
            report.setMaximumHeight(125)
            layout.addWidget(report)
        else:
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
            return (
                "Manage Pack IDs without a BIN. Select a BIN above to assign "
                "a pack or record history."
            )
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
        self.pack_assign_combo.setMaximumWidth(250)
        self.pack_assign_combo.addItem(_PACK_ID_PLACEHOLDER, None)
        self.pack_assign_combo.currentIndexChanged.connect(
            self._update_analysis_controls
        )
        self.pack_assign_combo.currentIndexChanged.connect(
            self._clear_pack_selection_error
        )
        self.pack_assign_button = QPushButton("Assign selected BIN")
        self.pack_assign_button.clicked.connect(self.assign_existing_pack)
        assignment_layout.addWidget(self.pack_assign_combo)
        assignment_layout.addWidget(self.pack_assign_button)
        assignment_layout.addStretch(1)
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

        lifecycle_group = QGroupBox("Archive, restore, or delete Pack ID")
        lifecycle_layout = QGridLayout(lifecycle_group)
        for row, (label, combo_name, button_name, caption, handler) in enumerate((
            ("Active:", "pack_archive_combo", "pack_archive_button", "Archive", self.archive_pack),
            ("Archived:", "pack_restore_combo", "pack_restore_button", "Restore", self.restore_pack),
            ("Delete Pack ID:", "pack_delete_combo", "pack_delete_button", "Delete permanently", self.delete_pack),
        )):
            combo = QComboBox()
            combo.addItem(_PACK_ID_PLACEHOLDER, None)
            combo.currentIndexChanged.connect(self._update_analysis_controls)
            if combo_name == "pack_delete_combo":
                combo.currentIndexChanged.connect(
                    lambda _index: self._update_delete_preview(selection_changed=True)
                )
            else:
                combo.currentIndexChanged.connect(self._clear_pack_selection_error)
            button = QPushButton(caption)
            button.clicked.connect(handler)
            setattr(self, combo_name, combo)
            setattr(self, button_name, button)
            lifecycle_layout.addWidget(QLabel(label), row, 0)
            lifecycle_layout.addWidget(combo, row, 1)
            lifecycle_layout.addWidget(button, row, 2)
        self.pack_delete_preview_text = QPlainTextEdit()
        self.pack_delete_preview_text.setReadOnly(True)
        self.pack_delete_preview_text.setMaximumHeight(80)
        self.pack_delete_preview_text.setPlainText(
            "Select a Pack ID to preview associated BIN logs and history."
        )
        lifecycle_layout.addWidget(self.pack_delete_preview_text, 3, 0, 1, 3)
        layout.addWidget(lifecycle_group)

        rename_group = QGroupBox("Rename existing Pack ID")
        # A compact three-row grid avoids an expanding action-layout row
        # squeezing the form fields and clipping the Rename button.
        rename_layout = QGridLayout(rename_group)
        rename_layout.setColumnStretch(1, 1)
        self.pack_rename_combo = QComboBox()
        self.pack_rename_combo.setMinimumWidth(250)
        self.pack_rename_combo.setMaximumWidth(350)
        self.pack_rename_combo.addItem(_PACK_ID_PLACEHOLDER, None)
        self.pack_rename_combo.currentIndexChanged.connect(
            self._update_analysis_controls
        )
        self.pack_rename_combo.currentIndexChanged.connect(
            self._clear_pack_selection_error
        )
        self.pack_rename_edit = QLineEdit()
        self.pack_rename_edit.setMinimumWidth(320)
        self.pack_rename_edit.setMaximumWidth(420)
        self.pack_rename_edit.setPlaceholderText("Replacement Pack ID")
        self.pack_rename_edit.textChanged.connect(self._update_analysis_controls)
        self.pack_rename_button = QPushButton("Rename globally")
        self.pack_rename_button.clicked.connect(self.rename_pack)
        rename_layout.addWidget(QLabel("Existing:"), 0, 0)
        rename_layout.addWidget(self.pack_rename_combo, 0, 1)
        rename_layout.addWidget(QLabel("Replacement:"), 1, 0)
        rename_layout.addWidget(self.pack_rename_edit, 1, 1)
        rename_layout.addWidget(QLabel("Effect:"), 2, 0)
        rename_effect = QLabel(
            "Updates the Pack ID in every saved BIN association that uses it."
        )
        rename_effect.setWordWrap(True)
        rename_layout.addWidget(rename_effect, 2, 1)
        rename_layout.addWidget(self.pack_rename_button, 2, 2)
        layout.addWidget(rename_group)

        history_group = QGroupBox("Record takeoff history")
        history_layout = QHBoxLayout(history_group)
        history_layout.addWidget(
            QLabel(
                "Adds supported AUTO, MANUAL and FBWA takeoff observations "
                "from the selected BIN to its assigned pack's history."
            ),
            1,
        )
        self.pack_record_history_button = QPushButton("Record takeoff history")
        self.pack_record_history_button.clicked.connect(self.record_pack_history_v2)
        history_layout.addWidget(self.pack_record_history_button)
        layout.addWidget(history_group)

    def _request_pack_lookup(self) -> None:
        """Load pack state and optionally resolve the selected BIN."""
        if self._analysis_thread is not None:
            self._pending_pack_lookup = self._selected_log
            self._pending_pack_lookup_requested = True
            self._refresh_pack_management_view("Association lookup pending.")
            return
        if self._selected_log is None:
            if not hasattr(self._pack_management_service, "lookup_packs"):
                return
            try:
                state = self._pack_management_service.lookup_packs()
            except (OSError, ValueError, RuntimeError) as exc:
                self._show_pack_message(str(exc), error=True)
            else:
                self._pack_management_succeeded(state)
            return
        path = self._selected_log
        self._pack_management_task = "lookup"
        self._refresh_pack_management_view(
            "Identifying source BIN…" if path is not None else "Loading Pack IDs…"
        )
        self._start_worker(
            "Battery Pack Management",
            path,
            self._pack_management_service.lookup if path is not None
            else lambda _unused: self._pack_management_service.lookup_packs(),
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
            "This updates every saved BIN association using this Pack ID.",
        ):
            return
        if (self._current_pack_state() != state
                or self.pack_rename_combo.currentData() != old_id
                or self.pack_rename_edit.text().strip() != new_id):
            self._show_pack_message("Pack selection changed; refresh and try again.", error=True)
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

    def record_pack_history_v2(self) -> None:
        """Confirm takeoff recording before starting its worker."""
        state = self._current_pack_state()
        if (state is None or state.log_path is None
                or state.association.state is not LogPackState.TRACKED
                or state.association.pack_id is None):
            return
        if not self._confirm_pack_action(
            "Record takeoff history",
            "Record supported AUTO, MANUAL and FBWA takeoff observations "
            "from this BIN into its assigned pack's history?\n\n"
            f"Source BIN: {state.log_path.name}\n"
            f"Assigned Pack ID: {state.association.pack_id}\n\n"
            "Existing observations will be preserved. Matching observations "
            "will not be duplicated. Conflicting evidence will stop recording.",
        ):
            return
        if self._current_pack_state() != state:
            self._show_pack_message("Pack selection changed; refresh and try again.", error=True)
            return
        self._start_pack_mutation(
            "history_v2", state,
            lambda _path: self._pack_management_service.record_history_v2(state),
        )

    def _change_pack_lifecycle(self, action: str, combo: QComboBox) -> None:
        state = self._current_pack_state()
        pack_id = combo.currentData()
        if state is None or not isinstance(pack_id, str):
            return
        detail = "Saved associations and historical observations are retained."
        if not self._confirm_pack_action(
            f"{action.title()} Battery Pack", f"{action.title()} Pack ID {pack_id}?\n\n{detail}"
        ):
            return
        if self._current_pack_state() != state or combo.currentData() != pack_id:
            self._show_pack_message("Pack selection changed; refresh and try again.", error=True)
            return
        self._start_pack_mutation(
            action, state,
            lambda _path: getattr(self._pack_management_service, action)(state, pack_id),
        )

    def archive_pack(self) -> None:
        self._change_pack_lifecycle("archive", self.pack_archive_combo)

    def restore_pack(self) -> None:
        self._change_pack_lifecycle("restore", self.pack_restore_combo)

    def delete_pack(self) -> None:
        state = self._current_pack_state()
        pack_id = self.pack_delete_combo.currentData()
        if state is None or not isinstance(pack_id, str):
            return
        try:
            preview = self._pack_management_service.preview_delete(state, pack_id)
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_pack_delete_error(str(exc))
            return
        if not self._confirm_pack_deletion(preview):
            return
        if self.pack_delete_combo.currentData() != pack_id or self._current_pack_state() != state:
            self._show_pack_delete_error("Pack selection changed; refresh and try again.")
            return
        self._start_pack_mutation(
            "delete", state,
            lambda _path: self._pack_management_service.delete(state, pack_id, preview),
        )

    def _confirm_pack_deletion(self, preview) -> bool:
        plan = preview.plan
        log_count = len(plan.log_fingerprints)
        history_count = len(plan.observation_ids) + len(plan.v2_observation_ids)
        retained_count = len(plan.retained_history_owners)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(f"Delete Pack ID — {plan.pack_id}?")
        dialog.setText(
            f"Delete Pack ID — {plan.pack_id}?\n\n"
            "This Pack ID has:\n\n"
            f"• {log_count} associated BIN {'log' if log_count == 1 else 'logs'}\n"
            f"• {history_count} battery history observations "
            f"(existing AUTO: {len(plan.observation_ids)}, "
            f"takeoff load: {len(plan.v2_observation_ids)})\n\n"
            "Associated BIN logs:\n"
            f"{self._associated_log_lines(preview)}\n\n"
            "Deleting this Pack ID will:\n\n"
            "• Remove the Pack ID.\n"
            "• Change its associated BIN logs to Not tracked.\n"
            "• Permanently delete only its owned battery history observations.\n"
            f"• Retain {retained_count} history "
            f"{'observation' if retained_count == 1 else 'observations'} "
            "owned by other Pack IDs.\n"
            "• Leave the original BIN files untouched.\n\n"
            "You can subsequently assign those BIN files to another Pack ID "
            "and record their battery history again."
        )
        cancel_button = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        delete_button = dialog.addButton("Delete Pack ID", QMessageBox.ButtonRole.DestructiveRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    @staticmethod
    def _associated_log_lines(preview) -> str:
        if not preview.associated_logs:
            return "• None"
        lines = []
        for log in preview.associated_logs:
            short_id = f"SHA-256 {log.fingerprint[:16]}…"
            names = ", ".join(log.filenames) if log.filenames else (
                f"Unknown filename — {short_id}"
            )
            suffix = "observation" if log.observation_count == 1 else "observations"
            lines.append(
                f"• {names} ({short_id}; {log.observation_count} "
                f"owned {suffix} to delete)"
            )
        return "\n".join(lines)

    def _clear_pack_selection_error(self, *_args) -> None:
        report = self.report_for("Battery Pack Management")
        if report.toPlainText().startswith("Battery Pack Management Error"):
            report.setPlainText("Pack selection changed. Choose an action.")
            self.statusBar().clearMessage()

    def _update_delete_preview(self, *, selection_changed: bool = False) -> None:
        if self.pack_delete_preview_text is None or self.pack_delete_combo is None:
            return
        if selection_changed:
            self._clear_pack_selection_error()
        self._pack_delete_preview = None
        pack_id = self.pack_delete_combo.currentData()
        state = self._current_pack_state()
        if not isinstance(pack_id, str):
            message = "Select a Pack ID to preview associated BIN logs and history."
        elif state is None:
            message = "Loading Pack IDs…"
        else:
            try:
                preview = self._pack_management_service.preview_delete(state, pack_id)
            except (OSError, ValueError, RuntimeError) as exc:
                message = f"Deletion blocked for {pack_id}: {exc}"
            else:
                self._pack_delete_preview = preview
                count = len(preview.plan.observation_ids) + len(preview.plan.v2_observation_ids)
                message = (
                    f"Pack ID: {pack_id}\n"
                    f"Associated BIN logs: {len(preview.associated_logs)}\n"
                    f"{self._associated_log_lines(preview)}\n"
                    f"Battery history observations to delete: {count} "
                    f"(existing AUTO: {len(preview.plan.observation_ids)}, "
                    f"takeoff load: {len(preview.plan.v2_observation_ids)})\n"
                    "Other Pack ID observations retained: "
                    f"{len(preview.plan.retained_history_owners)}"
                )
        self.pack_delete_preview_text.setPlainText(message)

    def _show_pack_delete_error(self, message: str) -> None:
        """Keep the report diagnostic and make a failed deletion visible."""
        self._show_pack_message(message, error=True)
        QMessageBox.warning(self, "Delete Pack ID failed", message)

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
            state = self._pack_management_state
            pack_ids = state.pack_ids if state is not None else ()
            archived_ids = state.archived_pack_ids if state is not None else ()
            delete_ids = (*pack_ids, *archived_ids)
        else:
            self.pack_selected_bin_value.setText(self._selected_log.name)
            state = self._pack_management_state
            if state is not None and state.log_path == self._selected_log:
                self.pack_association_value.setText(self._association_text(state))
                pack_ids = state.pack_ids
                archived_ids = state.archived_pack_ids
                delete_ids = (*state.pack_ids, *state.archived_pack_ids)
            else:
                self.pack_association_value.setText("Pending lookup")
                pack_ids = ()
                archived_ids = ()
                delete_ids = ()

        for combo in (self.pack_assign_combo, self.pack_rename_combo):
            if combo is not None:
                current = selected_pack_id or combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(_PACK_ID_PLACEHOLDER, None)
                for pack_id in pack_ids:
                    combo.addItem(pack_id, pack_id)
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
                combo.blockSignals(False)
        for combo, ids in (
            (self.pack_archive_combo, pack_ids),
            (self.pack_restore_combo, archived_ids),
            (self.pack_delete_combo, delete_ids),
        ):
            if combo is None:
                continue
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_PACK_ID_PLACEHOLDER, None)
            for pack_id in ids:
                combo.addItem(pack_id, pack_id)
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if message is not None:
            self.report_for("Battery Pack Management").setPlainText(message)
        self._update_analysis_controls()
        self._update_delete_preview()

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
            if state is None or state.log_path != self._selected_log:
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
        source_ready = pack_ready and self._selected_log is not None
        pack_ids = (
            self._pack_management_state.pack_ids
            if self._pack_management_state is not None
            else ()
        )
        delete_ids = (
            (*self._pack_management_state.pack_ids,
             *self._pack_management_state.archived_pack_ids)
            if self._pack_management_state is not None
            else ()
        )
        if self.pack_assign_button is not None:
            selected = (
                self.pack_assign_combo.currentData()
                if self.pack_assign_combo is not None
                else None
            )
            self.pack_assign_button.setEnabled(source_ready and selected in pack_ids)
        if self.pack_create_button is not None:
            self.pack_create_button.setEnabled(
                source_ready
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
                source_ready
                and association is not None
                and association.state is LogPackState.TRACKED
            )
        for combo, button, ids in (
            (self.pack_archive_combo, self.pack_archive_button, pack_ids),
            (self.pack_restore_combo, self.pack_restore_button,
             self._pack_management_state.archived_pack_ids if self._pack_management_state else ()),
            (self.pack_delete_combo, self.pack_delete_button, delete_ids),
        ):
            if button is not None:
                button.setEnabled(pack_ready and combo.currentData() in ids)
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
            if self._pack_management_task == "delete":
                self._show_pack_delete_error(str(exc))
            else:
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
            requested = self._pending_pack_lookup_requested
            self._pending_pack_lookup_requested = False
            if requested and pending == self._selected_log:
                self._request_pack_lookup()
            else:
                self._update_delete_preview()

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
            if isinstance(result, PackManagementResult) and result.changed:
                self._pack_performance.request_refresh()
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
        QSettings("ArduPlaneTools", "ArduPlaneTools").setValue(
            WINDOW_SIZE_KEY, self.size()
        )
        event.accept()
