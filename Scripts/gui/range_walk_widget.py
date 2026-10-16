"""Focused Qt controls for Range-Walk marker and history entry."""

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.range_walk import WalkSettings
from core.range_walk_history import StoredAdditionalWalk, StoredWalk1Baseline

from .range_walk_adapter import (
    AdditionalWalk,
    RangeWalkCsvInspection,
    RangeWalkInspectionRequest,
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    Walk1Baseline,
    analyse_range_walk_preview,
    create_additional_walk,
    create_walk1_baseline,
    format_additional_walk_summary,
    format_walk1_baseline_summary,
    inspect_range_walk_csv,
)
from .range_walk_setup import apply_parent_baseline, configure_walk_type


class RangeWalkPreviewWidget(QWidget):
    """One CSV source, calibration inputs and marker-candidate report."""

    def __init__(
        self,
        choose_source,
        detect,
        persist_baseline=None,
        load_history=None,
        parent=None,
    ):
        super().__init__(parent)
        self._persist_baseline = persist_baseline
        self._load_history = load_history
        self._source_path: Path | None = None
        self._inspection: RangeWalkCsvInspection | None = None
        self._result: RangeWalkPreviewResult | None = None
        self._saved_baseline: Walk1Baseline | None = None
        self._persisted_record: StoredWalk1Baseline | None = None
        self._persisted_walk: StoredAdditionalWalk | None = None
        self._history_records: dict[str, StoredWalk1Baseline] = {}
        self._applied_parent_baseline_id: str | None = None
        self._baseline_saved_dirty = False
        self._baseline_form_state = None
        self._current_walk_type = "baseline"
        self._persisted_dirty = False
        self._draft_revision = 0
        self._default_walk1_label = ""
        self._outcome = ""
        self._has_result = False
        self._busy = False
        self._busy_task: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        page1 = QWidget()
        page1_layout = QVBoxLayout(page1)
        page1_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(page1)

        notice = QLabel(
            "<b>Range-Walk Comparison</b><br>"
            "Compare repeatable radio range-walk recordings.<br>"
            "Select an EdgeTX CSV to detect markers and prepare a range walk.<br>"
            "The shared Source BIN selection does not apply."
        )
        notice.setWordWrap(True)
        page1_layout.addWidget(notice)
        self.preview_notice = notice
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("EdgeTX CSV:"))
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setObjectName("rangeWalkCsvPath")
        self.source_path_edit.setReadOnly(True)
        self.source_path_edit.setPlaceholderText("No EdgeTX CSV selected")
        source_layout.addWidget(self.source_path_edit, 1)
        self.choose_button = QPushButton("Choose CSV…")
        self.choose_button.setObjectName("rangeWalkChooseCsvButton")
        self.choose_button.clicked.connect(choose_source)
        source_layout.addWidget(self.choose_button)
        page1_layout.addLayout(source_layout)
        detection_group = QGroupBox()
        detection_layout = QVBoxLayout(detection_group)
        direction_heading = QLabel("Elevator marker direction")
        direction_heading.setObjectName("rangeWalkDirectionHeading")
        direction_heading_font = direction_heading.font()
        direction_heading_font.setBold(True)
        direction_heading.setFont(direction_heading_font)
        detection_layout.addWidget(direction_heading)
        self.direction_heading = direction_heading
        guidance = QLabel(
            "Choose the marker direction here; Detect markers runs detection. "
            "Automatic compares sustained holds and neutral returns in both "
            "Ele directions."
        )
        guidance.setWordWrap(True)
        detection_layout.addWidget(guidance)
        self.calibration_guidance = guidance
        mode_layout = QHBoxLayout()
        self.auto_button = QRadioButton("Automatic (recommended)")
        self.auto_button.setObjectName("rangeWalkAutoDirection")
        self.inverse_button = QRadioButton("Opposite direction")
        self.inverse_button.setObjectName("rangeWalkInverseDirection")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.auto_button)
        self.mode_group.addButton(self.inverse_button)
        self.auto_button.setChecked(True)
        mode_layout.addWidget(self.auto_button)
        mode_layout.addWidget(self.inverse_button)
        mode_layout.addStretch(1)
        detection_layout.addLayout(mode_layout)
        self.suggestion_label = QLabel("Choose a CSV to obtain calibration suggestions.")
        self.suggestion_label.setObjectName("rangeWalkCalibrationSuggestion")
        self.suggestion_label.setWordWrap(True)
        detection_layout.addWidget(self.suggestion_label)
        page1_layout.addWidget(detection_group)
        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.detect_button = QPushButton("Detect markers")
        self.detect_button.setObjectName("rangeWalkDetectMarkersButton")
        self.detect_button.clicked.connect(detect)
        action_layout.addWidget(self.detect_button)
        self.next_button = QPushButton("Next: Walk Setup")
        self.next_button.setObjectName("rangeWalkNextButton")
        self.next_button.clicked.connect(self._show_baseline_page)
        action_layout.addWidget(self.next_button)
        self.page1_history_button = QPushButton("History & Comparison")
        self.page1_history_button.setObjectName("rangeWalkPage1HistoryButton")
        self.page1_history_button.clicked.connect(self._show_history_page)
        action_layout.addWidget(self.page1_history_button)
        page1_layout.addLayout(action_layout)
        self.state_label = QLabel()
        self.state_label.setObjectName("rangeWalkPreviewState")
        self.state_label.setWordWrap(True)
        self.state_label.setMinimumHeight(38)
        page1_layout.addWidget(self.state_label)
        self.report = QPlainTextEdit()
        self.report.setObjectName("range_walk_preview_report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setPlainText(
            "Range-Walk Comparison\n\n"
            "Compare repeatable radio range-walk recordings.\n\n"
            "Select an EdgeTX CSV to detect markers and prepare a range walk.\n\n"
            "The shared Source BIN selection does not apply."
        )
        page1_layout.addWidget(self.report, 1)
        self._build_baseline_page()
        self._build_history_page()
        self._walk_type_changed()
        self.auto_button.clicked.connect(self._mode_changed)
        self.inverse_button.clicked.connect(self._mode_changed)
        self._update_controls()

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    @property
    def saved_baseline(self) -> Walk1Baseline | None:
        return self._saved_baseline

    @property
    def persisted_record(self) -> StoredWalk1Baseline | None:
        return self._persisted_record

    @property
    def draft_revision(self) -> int:
        return self._draft_revision

    def history_record(self, baseline_id: str) -> StoredWalk1Baseline | None:
        return self._history_records.get(baseline_id)

    def set_source(self, path: Path) -> None:
        self._invalidate_evidence(
            "CSV changed — any previous Walk 1 baseline was cleared."
        )
        self._source_path = path
        self._inspection = None
        self._outcome = ""
        self._has_result = False
        self.auto_button.setChecked(True)
        self.source_path_edit.setText(str(path))
        self.source_path_edit.setToolTip(str(path))
        self.source_path_edit.setCursorPosition(0)
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Selected: {path}\n\n"
            "Reading sustained elevator evidence before detection."
        )
        self._update_controls()

    def set_inspection(self, inspection: RangeWalkCsvInspection) -> None:
        self._inspection = inspection
        self._outcome = ""
        self._has_result = False
        self.report.setPlainText(self._inspection_text(inspection))
        self._update_suggestion_label()
        self._update_controls()

    def set_busy(self, busy: bool, task: str | None = None) -> None:
        self._busy = busy
        self._busy_task = task if busy else None
        self.detect_button.setText(
            "Detecting…" if busy and task == "detect" else "Detect markers"
        )
        self._update_controls()

    def show_inspection_busy(self) -> None:
        assert self._source_path is not None
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Reading {self._source_path} to inspect its recorded Ele range…\n\n"
            "Auto will evaluate both sustained elevator directions."
        )

    def show_busy(self) -> None:
        assert self._source_path is not None
        self._invalidate_evidence(
            "Marker detection restarted — any previous Walk 1 baseline was cleared."
        )
        self._has_result = False
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Reading {self._source_path} and detecting markers…\n\n"
            "The GUI remains available; no progress percentage is available."
        )

    def show_result(self, result: RangeWalkPreviewResult) -> None:
        self._result = result
        self._has_result = True
        self._outcome = (
            "Detection completed — "
            f"{_direction_label(result.direction_used)} direction; "
            f"{len(result.markers)} marker candidate(s)."
        )
        self.report.setPlainText(result.text)
        self._populate_candidate_mappings(result)
        self._update_controls()

    def show_error(self, message: str, task: str | None) -> None:
        if task == "detect":
            self._result = None
        self._has_result = False
        operation = "Detection" if task == "detect" else "CSV inspection"
        self._outcome = (
            f"{operation} failed — {message} The selected CSV is retained."
        )
        self.report.setPlainText(
            "Range-Walk CSV Preview Error\n"
            "============================\n"
            f"{message}"
        )
        self._update_controls()

    def _mode_changed(self) -> None:
        had_result = self._has_result
        self._invalidate_evidence(
            "Detection direction changed — any previous Walk 1 baseline was cleared."
        )
        self._has_result = False
        self._outcome = (
            "Detection mode changed — previous result cleared. Choose Detect markers."
            if had_result
            else ""
        )
        if self._inspection is not None:
            message = (
                "\n\nDetection mode changed; the previous result is no longer "
                "shown. Choose Detect markers to run the selected mode."
                if had_result
                else ""
            )
            self.report.setPlainText(self._inspection_text(self._inspection) + message)
        self._update_suggestion_label()
        self._update_controls()

    def _build_baseline_page(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        baseline_layout = QVBoxLayout(page)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        navigation = QHBoxLayout()
        self.back_button = QPushButton("Back: CSV & Markers")
        self.back_button.setObjectName("rangeWalkBackButton")
        self.back_button.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        navigation.addWidget(self.back_button)
        navigation.addStretch(1)
        self.baseline_history_button = QPushButton("Next: History & Comparison")
        self.baseline_history_button.setObjectName("rangeWalkBaselineHistoryButton")
        self.baseline_history_button.clicked.connect(self._show_history_page)
        navigation.addWidget(self.baseline_history_button)
        baseline_layout.addLayout(navigation)
        heading = QLabel("<h2>Walk Setup &amp; Landmarks</h2>")
        self.baseline_heading = heading
        baseline_layout.addWidget(heading)
        explanation = QLabel(
            "Walk 1 records the baseline radio configuration and establishes "
            "the five physical landmarks. Landmark 5 is the safe turnaround. "
            "This draft is stored in memory only."
        )
        self.baseline_explanation = explanation
        explanation.setWordWrap(True)
        baseline_layout.addWidget(explanation)
        self.baseline_evidence_label = QLabel(
            "No detected marker evidence is available."
        )
        self.baseline_evidence_label.setObjectName("rangeWalkBaselineEvidence")
        self.baseline_evidence_label.setWordWrap(True)
        baseline_layout.addWidget(self.baseline_evidence_label)

        workflow = QFormLayout()
        self.walk_type_combo = QComboBox()
        self.walk_type_combo.setObjectName("rangeWalkSetupType")
        self.walk_type_combo.addItem("Create a new Walk 1 baseline", "baseline")
        self.walk_type_combo.addItem(
            "Record an additional walk against a saved baseline", "additional"
        )
        workflow.addRow("Workflow:", self.walk_type_combo)
        self.parent_baseline_combo = QComboBox()
        self.parent_baseline_combo.setObjectName("rangeWalkParentBaseline")
        workflow.addRow("Saved Walk 1 baseline:", self.parent_baseline_combo)
        self.parent_baseline_label = workflow.labelForField(self.parent_baseline_combo)
        self.parent_reference = QPlainTextEdit()
        self.parent_reference.setObjectName("rangeWalkParentReference")
        self.parent_reference.setReadOnly(True)
        self.parent_reference.setMaximumHeight(180)
        workflow.addRow("Baseline reference:", self.parent_reference)
        self.parent_reference_label = workflow.labelForField(self.parent_reference)
        baseline_layout.addLayout(workflow)
        metadata = QFormLayout()
        self.walk1_label_edit = QLineEdit()
        self.walk1_label_edit.setObjectName("rangeWalkBaselineLabel")
        self.antenna_edit = QLineEdit()
        self.antenna_edit.setObjectName("rangeWalkBaselineAntenna")
        self.antenna_edit.setPlaceholderText(
            "Receiver, antennas, placement and orientation"
        )
        self.walk_label = QLabel("Walk 1 label (optional):")
        metadata.addRow(self.walk_label, self.walk1_label_edit)
        self.antenna_label = QLabel("Baseline radio configuration:*")
        metadata.addRow(self.antenna_label, self.antenna_edit)
        baseline_layout.addLayout(metadata)

        mapping_group = QGroupBox("Five physical landmarks")
        mapping_layout = QVBoxLayout(mapping_group)
        mapping_help = QLabel(
            "Map five distinct candidates in chronological order. Extra candidates "
            "remain excluded; missing markers are never manufactured."
        )
        mapping_help.setWordWrap(True)
        mapping_layout.addWidget(mapping_help)
        self.candidate_combos: list[QComboBox] = []
        self.landmark_name_edits: list[QLineEdit] = []
        self.candidate_evidence_labels: list[QLabel] = []
        self.landmark_title_labels: list[QLabel] = []
        for position in range(1, 6):
            row = QHBoxLayout()
            title = f"Landmark {position}"
            if position == 5:
                title += " (turnaround)"
            title_label = QLabel(title + ":")
            row.addWidget(title_label)
            combo = QComboBox()
            combo.setObjectName(f"rangeWalkLandmark{position}Candidate")
            combo.setMinimumContentsLength(12)
            row.addWidget(combo)
            name = QLineEdit()
            name.setObjectName(f"rangeWalkLandmark{position}Name")
            name.setPlaceholderText("Physical landmark name (required)")
            row.addWidget(name, 1)
            evidence = QLabel("No candidate selected")
            evidence.setObjectName(f"rangeWalkLandmark{position}Evidence")
            evidence.setMinimumWidth(245)
            row.addWidget(evidence)
            mapping_layout.addLayout(row)
            self.candidate_combos.append(combo)
            self.landmark_name_edits.append(name)
            self.candidate_evidence_labels.append(evidence)
            self.landmark_title_labels.append(title_label)
            combo.currentIndexChanged.connect(self._mapping_changed)
            name.textChanged.connect(self._draft_changed)
        baseline_layout.addWidget(mapping_group)

        self.rf_settings_group = QGroupBox("RF Settings (expandable; optional)")
        self.rf_settings_group.setCheckable(True)
        self.rf_settings_group.setChecked(False)
        rf_title_font = self.rf_settings_group.font()
        rf_title_font.setPointSizeF(rf_title_font.pointSizeF() + 1.0)
        self.rf_settings_group.setFont(rf_title_font)
        rf_outer = QVBoxLayout(self.rf_settings_group)
        self.rf_settings_content = QWidget()
        rf_form = QFormLayout(self.rf_settings_content)
        self.tx_power_edit = QLineEdit()
        self.packet_rate_edit = QLineEdit()
        self.rf_mode_edit = QLineEdit()
        self.dynamic_power_edit = QLineEdit()
        rf_form.addRow("Configured TX power:", self.tx_power_edit)
        rf_form.addRow("Configured packet rate:", self.packet_rate_edit)
        rf_form.addRow("Configured RF mode/band:", self.rf_mode_edit)
        rf_form.addRow("Dynamic TX power state:", self.dynamic_power_edit)
        rf_outer.addWidget(self.rf_settings_content)
        normal_font = self.font()
        normal_font.setPointSizeF(normal_font.pointSizeF())
        self.rf_settings_content.setFont(normal_font)
        warning = QLabel(
            "Unknown values are allowed, but unknown or mismatched settings prevent "
            "later claims of like-for-like RF comparison. Values are operator-entered; "
            "telemetry TPWR/RFMD is not used as configured settings."
        )
        warning.setWordWrap(True)
        rf_outer.addWidget(warning)
        warning.setFont(normal_font)
        self.rf_settings_group.toggled.connect(self.rf_settings_content.setVisible)
        self.rf_settings_content.setVisible(False)
        for field in (
            self.tx_power_edit,
            self.packet_rate_edit,
            self.rf_mode_edit,
            self.dynamic_power_edit,
            self.antenna_edit,
            self.walk1_label_edit,
        ):
            field.textChanged.connect(self._draft_changed)
        baseline_layout.addWidget(self.rf_settings_group)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_baseline_button = QPushButton("Save Walk 1")
        self.save_baseline_button.setObjectName("rangeWalkSaveBaselineButton")
        self.save_baseline_button.clicked.connect(self._save_baseline)
        save_row.addWidget(self.save_baseline_button)
        baseline_layout.addLayout(save_row)
        self.baseline_state_label = QLabel(
            "Incomplete draft — detect markers on Page 1."
        )
        self.baseline_state_label.setObjectName("rangeWalkBaselineState")
        self.baseline_state_label.setWordWrap(True)
        baseline_layout.addWidget(self.baseline_state_label)
        self.baseline_summary = QPlainTextEdit()
        self.baseline_summary.setObjectName("rangeWalkBaselineSummary")
        self.baseline_summary.setReadOnly(True)
        self.baseline_summary.setMinimumHeight(180)
        baseline_layout.addWidget(self.baseline_summary)
        self.walk_type_combo.currentIndexChanged.connect(self._walk_type_changed)
        self.parent_baseline_combo.currentIndexChanged.connect(
            self._parent_baseline_changed
        )

    def _build_history_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.pages.addWidget(page)
        navigation = QHBoxLayout()
        self.history_back_button = QPushButton("Back: Walk Setup")
        self.history_back_button.setObjectName("rangeWalkHistoryBackButton")
        self.history_back_button.clicked.connect(self._history_back)
        navigation.addWidget(self.history_back_button)
        navigation.addStretch(1)
        self.refresh_history_button = QPushButton("Refresh history")
        self.refresh_history_button.setObjectName("rangeWalkRefreshHistoryButton")
        self.refresh_history_button.clicked.connect(self._request_history)
        navigation.addWidget(self.refresh_history_button)
        layout.addLayout(navigation)
        layout.addWidget(QLabel("<h2>History &amp; Comparison</h2>"))
        notice = QLabel(
            "Saved Walk 1 baselines and associated later walks are read-only. "
            "RF comparisons are not yet available."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.history_report = QPlainTextEdit()
        self.history_report.setObjectName("rangeWalkHistoryReport")
        self.history_report.setReadOnly(True)
        self.history_report.setPlainText(
            "Range-Walk History & Comparison\n\nOpen this page to load history.\n"
            "RF comparisons are not yet available."
        )
        layout.addWidget(self.history_report, 1)

    def _show_baseline_page(self) -> None:
        if self._result is None:
            return
        self.pages.setCurrentIndex(1)

    def _show_history_page(self) -> None:
        self.pages.setCurrentIndex(2)
        self._request_history()

    def _request_history(self) -> None:
        if self._load_history is not None:
            self._load_history()

    def _history_back(self) -> None:
        self.pages.setCurrentIndex(1 if self._result is not None else 0)

    def _walk_type_changed(self) -> None:
        configure_walk_type(self)

    def _parent_baseline_changed(self) -> None:
        apply_parent_baseline(self)

    def _populate_candidate_mappings(self, result: RangeWalkPreviewResult) -> None:
        count = len(result.markers)
        self.baseline_evidence_label.setText(
            f"{count} chronological candidate(s) detected in "
            f"{_direction_label(result.direction_used)} direction from "
            f"{result.source_path.name}."
        )
        default_label = f"Walk 1 — {result.source_path.stem}"
        if (
            not self.walk1_label_edit.text().strip()
            or self.walk1_label_edit.text() == self._default_walk1_label
        ):
            self.walk1_label_edit.setText(default_label)
        self._default_walk1_label = default_label
        for position, combo in enumerate(self.candidate_combos, start=1):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(
                "Missing / unconfirmed"
                if self.walk_type_combo.currentData() == "additional"
                else "Select candidate…",
                None,
            )
            for number, marker in enumerate(result.markers, start=1):
                combo.addItem(
                    "Candidate "
                    f"{number} — {marker.onset.time().isoformat(timespec='seconds')}",
                    number,
                )
            combo.setCurrentIndex(
                0
                if self.walk_type_combo.currentData() == "additional"
                else position if position <= count else 0
            )
            combo.blockSignals(False)
            self._update_candidate_evidence(position - 1)
        self._saved_baseline = None
        self._persisted_walk = None
        self.baseline_summary.clear()
        if self.walk_type_combo.currentData() == "additional":
            self.baseline_state_label.setText(
                "Incomplete draft — explicitly assign each confirmed marker to its "
                "physical baseline landmark; leave missing evidence unassigned."
            )
        elif count < 5:
            self.baseline_state_label.setText(
                f"Incomplete draft — only {count} candidates were detected; a "
                "complete Walk 1 baseline requires five."
            )
        elif count > 5:
            self.baseline_state_label.setText(
                f"Incomplete draft — choose exactly five of {count} candidates in "
                "chronological order, excluding extras."
            )
        else:
            self.baseline_state_label.setText(
                "Incomplete draft — candidates 1–5 are mapped chronologically; "
                "enter the required physical metadata."
            )

    def _mapping_changed(self) -> None:
        combo = self.sender()
        if combo in self.candidate_combos:
            self._update_candidate_evidence(self.candidate_combos.index(combo))
        self._draft_changed()

    def _update_candidate_evidence(self, index: int) -> None:
        number = self.candidate_combos[index].currentData()
        if self._result is None or number is None:
            self.candidate_evidence_labels[index].setText(
                "Missing marker evidence"
                if self.walk_type_combo.currentData() == "additional"
                else "No candidate selected"
            )
            return
        marker = self._result.markers[number - 1]
        self.candidate_evidence_labels[index].setText(
            f"{marker.onset:%H:%M:%S} → {marker.release:%H:%M:%S} "
            f"({marker.hold_s:.1f} s)"
        )

    def _save_baseline(self) -> None:
        if self._result is None:
            self.baseline_state_label.setText(
                "Incomplete draft — no current marker detection is available."
            )
            return
        additional = self.walk_type_combo.currentData() == "additional"
        try:
            if additional:
                parent = self._history_records.get(
                    self.parent_baseline_combo.currentData()
                )
                if parent is None:
                    raise ValueError("Select a saved Walk 1 baseline")
                saved = create_additional_walk(
                    self._result,
                    parent,
                    tuple(combo.currentData() for combo in self.candidate_combos),
                    self.antenna_edit.text(),
                    self.walk1_label_edit.text(),
                )
            else:
                saved = create_walk1_baseline(
                    self._result,
                    tuple(combo.currentData() for combo in self.candidate_combos),
                    tuple(field.text() for field in self.landmark_name_edits),
                    self.antenna_edit.text(),
                    self.walk1_label_edit.text(),
                    WalkSettings(
                        self.tx_power_edit.text().strip(),
                        self.packet_rate_edit.text().strip(),
                        self.rf_mode_edit.text().strip(),
                        self.dynamic_power_edit.text().strip(),
                    ),
                )
        except ValueError as exc:
            self.baseline_state_label.setText(f"Incomplete draft — {exc}.")
            return
        if self._persist_baseline is None:
            if additional:
                self.show_persisted_additional_walk(saved, parent, None)
            else:
                self.show_persisted_baseline(saved, None)
        else:
            self._persist_baseline(saved, self._persisted_record)

    def show_save_busy(self) -> None:
        self.baseline_state_label.setText(
            "Saving Range-Walk evidence and preserving the source CSV…"
        )

    def show_persisted_baseline(
        self,
        baseline: Walk1Baseline,
        record,
        *,
        updated: bool = False,
    ) -> None:
        self._saved_baseline = baseline
        self._persisted_record = record
        self._persisted_dirty = False
        if record is None:
            self.baseline_state_label.setText(
                "Walk 1 baseline validated in memory only."
            )
        else:
            self.baseline_state_label.setText(
                f"Walk 1 baseline {'updated' if updated else 'saved'} — "
                f"ID {record.baseline_id}. Source CSV preserved."
            )
        summary = format_walk1_baseline_summary(baseline)
        if record is not None:
            summary += (
                "\nBaseline ID: "
                f"{record.baseline_id}\nManaged CSV: {record.stored_csv_path}"
            )
        self.baseline_summary.setPlainText(summary)

    def show_persisted_additional_walk(
        self,
        walk: AdditionalWalk,
        parent: StoredWalk1Baseline,
        record: StoredAdditionalWalk | None,
    ) -> None:
        self._persisted_walk = record
        if record is None:
            state = "Additional walk validated in memory only."
        else:
            state = (
                f"Additional walk saved — ID {record.walk_id}. Source CSV preserved."
            )
        self.baseline_state_label.setText(state)
        summary = format_additional_walk_summary(walk, parent)
        if record is not None:
            summary += (
                f"\nWalk ID: {record.walk_id}\nManaged CSV: "
                f"{record.stored_csv_path}"
            )
        self.baseline_summary.setPlainText(summary)
        self._update_controls()

    def show_persistence_error(self, message: str) -> None:
        self.baseline_state_label.setText(f"Range-Walk save failed — {message}")

    def retain_persisted_identity_for_newer_draft(
        self,
        baseline: Walk1Baseline,
        record: StoredWalk1Baseline,
    ) -> None:
        """Retain a completed write without replacing newer visible form state."""
        self._saved_baseline = baseline
        self._persisted_record = record
        self._persisted_dirty = True
        self.baseline_summary.clear()
        self.baseline_state_label.setText(
            "Saved Walk 1, but the visible draft changed while saving; review and "
            "update saved Walk 1 again."
        )
        self._update_controls()

    def retain_persisted_walk_for_newer_draft(
        self, record: StoredAdditionalWalk
    ) -> None:
        """Retain a completed later-walk write without replacing newer form state."""
        self._persisted_walk = record
        self.baseline_summary.clear()
        self.baseline_state_label.setText(
            "Additional walk was saved, but the visible draft changed while "
            "saving; the newer draft was not persisted."
        )
        self._update_controls()

    def show_history_busy(self) -> None:
        self.history_report.setPlainText(
            "Loading and validating saved Range-Walk history…"
        )

    def show_history(
        self,
        text: str,
        records: tuple[StoredWalk1Baseline, ...] = (),
    ) -> None:
        selected_id = self.parent_baseline_combo.currentData()
        self._history_records = {record.baseline_id: record for record in records}
        self.parent_baseline_combo.blockSignals(True)
        self.parent_baseline_combo.clear()
        self.parent_baseline_combo.addItem("Select saved baseline…", None)
        for record in records:
            self.parent_baseline_combo.addItem(
                f"{record.label} — {record.baseline_id}", record.baseline_id
            )
        selected_index = self.parent_baseline_combo.findData(selected_id)
        self.parent_baseline_combo.setCurrentIndex(max(0, selected_index))
        self.parent_baseline_combo.blockSignals(False)
        self.history_report.setPlainText(text)
        self._parent_baseline_changed()

    def show_history_error(self, message: str) -> None:
        self.history_report.setPlainText(
            "Range-Walk History Error\n"
            "========================\n"
            f"{message}\n\nComparisons are not yet available."
        )

    def _draft_changed(self) -> None:
        self._draft_revision += 1
        if self.walk_type_combo.currentData() == "additional":
            self._update_controls()
            return
        if self._persisted_record is not None:
            self._persisted_dirty = True
            self.baseline_state_label.setText(
                "Incomplete draft — saved metadata or mapping changed; update saved "
                "Walk 1."
            )
            self._update_controls()
            return
        if self._saved_baseline is None:
            return
        self._saved_baseline = None
        self.baseline_state_label.setText(
            "Incomplete draft — saved metadata or mapping changed; save Walk 1 again."
        )
        self.baseline_summary.clear()

    def _invalidate_evidence(self, message: str) -> None:
        self._draft_revision += 1
        self._result = None
        self._saved_baseline = None
        self._persisted_record = None
        self._persisted_walk = None
        self._persisted_dirty = False
        if hasattr(self, "next_button"):
            self.next_button.setEnabled(False)
            self.baseline_state_label.setText(f"Incomplete draft — {message}")
            self.baseline_summary.clear()
            self.pages.setCurrentIndex(0)

    @staticmethod
    def _inspection_text(inspection: RangeWalkCsvInspection) -> str:
        suggestions = inspection.calibration
        return (
            "Range-Walk CSV / marker preview\n\n"
            f"Source CSV: {inspection.source_path.name}\n"
            f"Path: {inspection.source_path}\n"
            f"Radio-local recording: {inspection.recording_start} to "
            f"{inspection.recording_end}\n"
            f"CSV rows: {inspection.row_count}\n"
            f"Observed Ele range: {inspection.ele_min:g} to "
            f"{inspection.ele_max:g}\n\n"
            "These extrema are calibration clues only; isolated extrema are not "
            "used as calibrated endpoints.\n"
            f"{suggestions.explanation}"
        )

    def _update_suggestion_label(self) -> None:
        if self._inspection is None:
            text = "Choose a CSV to obtain calibration suggestions."
        else:
            suggestions = self._inspection.calibration
            neutral = _format_suggestion(suggestions.neutral)
            mode = (
                "Opposite direction"
                if self.inverse_button.isChecked()
                else "Automatic"
            )
            text = (
                f"Sustained neutral: {neutral}; higher endpoint: "
                f"{_format_suggestion(suggestions.high)}; lower endpoint: "
                f"{_format_suggestion(suggestions.low)}. {suggestions.explanation} "
                f"Mode: {mode}."
            )
        self.suggestion_label.setText(text)

    def _update_controls(self) -> None:
        available = not self._busy
        self.choose_button.setEnabled(available)
        ready = self._inspection is not None
        self.detect_button.setEnabled(available and ready)
        self.next_button.setEnabled(available and self._result is not None)
        self.save_baseline_button.setEnabled(
            available
            and self._result is not None
            and self._persisted_walk is None
            and (
                self.walk_type_combo.currentData() == "additional"
                or self._persisted_record is None
                or self._persisted_dirty
            )
        )
        self.back_button.setEnabled(available)
        self.baseline_history_button.setEnabled(available)
        self.page1_history_button.setEnabled(available)
        self.history_back_button.setEnabled(available)
        self.refresh_history_button.setEnabled(available)
        self.save_baseline_button.setText(
            "Saving…"
            if self._busy and self._busy_task == "save"
            else (
                "Save additional walk"
                if self.walk_type_combo.currentData() == "additional"
                else "Update saved Walk 1"
                if self._persisted_record is not None and self._persisted_dirty
                else "Save Walk 1"
            )
        )
        self.refresh_history_button.setText(
            "Loading…"
            if self._busy and self._busy_task == "history"
            else "Refresh history"
        )
        self.auto_button.setEnabled(available)
        self.inverse_button.setEnabled(available)
        self.walk_type_combo.setEnabled(available)
        self.parent_baseline_combo.setEnabled(
            available and self.walk_type_combo.currentData() == "additional"
        )
        for field in (
            self.walk1_label_edit,
            self.antenna_edit,
            *self.landmark_name_edits,
            self.tx_power_edit,
            self.packet_rate_edit,
            self.rf_mode_edit,
            self.dynamic_power_edit,
            *self.candidate_combos,
        ):
            field.setEnabled(available)
        self.rf_settings_group.setEnabled(available)
        if self._busy:
            if self._busy_task == "inspect":
                state = "Reading selected CSV and observed Ele range…"
            elif self._busy_task == "detect":
                state = "Detection running…"
            else:
                state = "Range-Walk storage operation running…"
        elif self._source_path is None:
            state = "No CSV selected — choose one EdgeTX transmitter log."
        elif self._outcome:
            state = self._outcome
        elif self._inspection is None:
            state = "CSV selected — observed Ele range is not yet available."
        else:
            mode = (
                "Opposite direction"
                if self.inverse_button.isChecked()
                else "Automatic"
            )
            state = f"Ready to detect marker candidates in {mode} mode."
        self.state_label.setText(state)


def _format_suggestion(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value:g}"


def _direction_label(direction: str) -> str:
    return "higher (+Ele)" if direction == "higher" else "lower (-Ele)"
