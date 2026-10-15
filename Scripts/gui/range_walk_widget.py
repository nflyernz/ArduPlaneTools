"""Focused Qt controls for Range-Walk CSV marker preview."""

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.range_walk import WalkSettings
from core.range_walk_history import StoredWalk1Baseline

from .range_walk_adapter import (
    RangeWalkCsvInspection,
    RangeWalkInspectionRequest,
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    Walk1Baseline,
    analyse_range_walk_preview,
    create_walk1_baseline,
    format_walk1_baseline_summary,
    inspect_range_walk_csv,
)
from .range_walk_history_adapter import (
    RangeWalkHistoryRequest,
    RangeWalkHistoryResult,
    RangeWalkHistoryService,
    SaveWalk1Request,
    SavedWalk1Result,
    UpdateWalk1Request,
)


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
            "<b>CSV/marker preview only — comparison not yet connected</b><br>"
            "Candidates are calibrated elevator holds, not confirmed landmarks. "
            "The shared aircraft BIN selection does not apply."
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
        detection_group = QGroupBox("Elevator marker direction")
        detection_layout = QVBoxLayout(detection_group)
        guidance = QLabel(
            "Auto compares complete sustained holds and neutral returns in both "
            "Ele directions. Use Inverse to inspect the opposite direction."
        )
        guidance.setWordWrap(True)
        detection_layout.addWidget(guidance)
        self.calibration_guidance = guidance
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Detection:"))
        self.auto_button = QPushButton("Auto")
        self.auto_button.setObjectName("rangeWalkAutoDirection")
        self.auto_button.setCheckable(True)
        self.inverse_button = QPushButton("Inverse")
        self.inverse_button.setObjectName("rangeWalkInverseDirection")
        self.inverse_button.setCheckable(True)
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
        self.next_button = QPushButton("Next: Walk 1 Setup")
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
            "Range-Walk CSV / marker preview\n\n"
            "Choose one EdgeTX CSV, then use Auto or Inverse marker detection."
        )
        page1_layout.addWidget(self.report, 1)
        self._build_baseline_page()
        self._build_history_page()
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
        heading = QLabel("<h2>Walk 1 — Baseline &amp; Landmarks</h2>")
        baseline_layout.addWidget(heading)
        explanation = QLabel(
            "Walk 1 records the baseline radio configuration and establishes "
            "the five physical landmarks. Landmark 5 is the safe turnaround. "
            "This draft is stored in memory only."
        )
        explanation.setWordWrap(True)
        baseline_layout.addWidget(explanation)
        self.baseline_evidence_label = QLabel(
            "No detected marker evidence is available."
        )
        self.baseline_evidence_label.setObjectName("rangeWalkBaselineEvidence")
        self.baseline_evidence_label.setWordWrap(True)
        baseline_layout.addWidget(self.baseline_evidence_label)
        metadata = QFormLayout()
        self.walk1_label_edit = QLineEdit()
        self.walk1_label_edit.setObjectName("rangeWalkBaselineLabel")
        self.antenna_edit = QLineEdit()
        self.antenna_edit.setObjectName("rangeWalkBaselineAntenna")
        self.antenna_edit.setPlaceholderText(
            "Receiver, antennas, placement and orientation"
        )
        metadata.addRow("Walk 1 label (optional):", self.walk1_label_edit)
        metadata.addRow("Baseline radio configuration:*", self.antenna_edit)
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
        for position in range(1, 6):
            row = QHBoxLayout()
            title = f"Landmark {position}"
            if position == 5:
                title += " (turnaround)"
            row.addWidget(QLabel(title + ":"))
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

    def _build_history_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.pages.addWidget(page)
        navigation = QHBoxLayout()
        self.history_back_button = QPushButton("Back: Walk 1 Setup")
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
            "Saved Walk 1 baselines are read-only. Comparisons are not yet available."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.history_report = QPlainTextEdit()
        self.history_report.setObjectName("rangeWalkHistoryReport")
        self.history_report.setReadOnly(True)
        self.history_report.setPlainText(
            "Range-Walk History & Comparison\n\nOpen this page to load history.\n"
            "Comparisons are not yet available."
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
            combo.addItem("Select candidate…", None)
            for number, marker in enumerate(result.markers, start=1):
                combo.addItem(
                    "Candidate "
                    f"{number} — {marker.onset.time().isoformat(timespec='seconds')}",
                    number,
                )
            combo.setCurrentIndex(position if position <= count else 0)
            combo.blockSignals(False)
            self._update_candidate_evidence(position - 1)
        self._saved_baseline = None
        self.baseline_summary.clear()
        if count < 5:
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
            self.candidate_evidence_labels[index].setText("No candidate selected")
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
        try:
            baseline = create_walk1_baseline(
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
            self._saved_baseline = None
            self.baseline_state_label.setText(f"Incomplete draft — {exc}.")
            return
        if self._persist_baseline is None:
            self.show_persisted_baseline(baseline, None)
        else:
            self._persist_baseline(baseline, self._persisted_record)

    def show_save_busy(self) -> None:
        self.baseline_state_label.setText(
            "Saving Walk 1 baseline and preserving the source CSV…"
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

    def show_persistence_error(self, message: str) -> None:
        self.baseline_state_label.setText(f"Walk 1 save failed — {message}")

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

    def show_history_busy(self) -> None:
        self.history_report.setPlainText(
            "Loading and validating saved Range-Walk history…"
        )

    def show_history(self, text: str) -> None:
        self.history_report.setPlainText(text)

    def show_history_error(self, message: str) -> None:
        self.history_report.setPlainText(
            "Range-Walk History Error\n"
            "========================\n"
            f"{message}\n\nComparisons are not yet available."
        )

    def _draft_changed(self) -> None:
        self._draft_revision += 1
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
            text = (
                f"Sustained neutral: {neutral}; higher endpoint: "
                f"{_format_suggestion(suggestions.high)}; lower endpoint: "
                f"{_format_suggestion(suggestions.low)}. {suggestions.explanation} "
                f"Mode: {'Inverse' if self.inverse_button.isChecked() else 'Auto'}."
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
            and (self._persisted_record is None or self._persisted_dirty)
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
                "Update saved Walk 1"
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
            mode = "Inverse" if self.inverse_button.isChecked() else "Auto"
            state = f"Ready to detect marker candidates in {mode} mode."
        self.state_label.setText(state)


def _format_suggestion(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value:g}"


def _direction_label(direction: str) -> str:
    return "higher (+Ele)" if direction == "higher" else "lower (-Ele)"


class RangeWalkPreviewController:
    """Run marker previews through MainWindow's shared one-shot worker."""

    analysis_name = "Range-Walk Comparison"

    def __init__(
        self,
        adapter,
        inspection_adapter,
        history_service,
        start_worker,
        is_busy,
        show_status,
    ):
        self.adapter = adapter or analyse_range_walk_preview
        self.inspection_adapter = inspection_adapter or inspect_range_walk_csv
        self.history_service = history_service or RangeWalkHistoryService()
        self.start_worker = start_worker
        self.is_busy = is_busy
        self.show_status = show_status
        self.widget: RangeWalkPreviewWidget | None = None
        self._request_id = 0
        self._task: str | None = None
        self._pending_inspection: Path | None = None
        self._pending_save_revision: int | None = None

    def create_widget(self, parent=None) -> RangeWalkPreviewWidget:
        widget = RangeWalkPreviewWidget(
            self.choose_source,
            self.request_preview,
            self.request_persist,
            self.request_history,
            parent,
        )
        self.widget = widget
        return widget

    def choose_source(self) -> None:
        widget = self._require_widget()
        if self.is_busy():
            return
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            widget,
            "Select EdgeTX range-walk CSV",
            str(widget.source_path.parent) if widget.source_path else "",
            "EdgeTX CSV files (*.csv *.CSV)",
        )
        if file_name:
            self.select_source(Path(file_name))

    def select_source(self, path: Path) -> bool:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            self._source_error(f"CSV selection rejected: not an existing file: {source}")
            return False
        if source.suffix.lower() != ".csv":
            self._source_error("CSV selection rejected: file must have a .csv extension")
            return False
        self._request_id += 1
        self._require_widget().set_source(source)
        self.show_status(f"Range-Walk preview CSV selected — {source}")
        if self.is_busy():
            self._pending_inspection = source
        else:
            self._start_inspection(source)
        return True

    def request_preview(self) -> None:
        widget = self._require_widget()
        if self.is_busy() or widget.source_path is None:
            return
        self._request_id += 1
        request = RangeWalkPreviewRequest(
            widget.source_path,
            widget.inverse_button.isChecked(),
            self._request_id,
        )
        self._task = "detect"
        self.start_worker(self.analysis_name, request, self.adapter)
        widget.show_busy()
        self.show_status(f"Detecting marker candidates — {widget.source_path}")

    def request_persist(
        self,
        baseline: Walk1Baseline,
        expected_record: StoredWalk1Baseline | None,
    ) -> None:
        if self.is_busy():
            return
        self._request_id += 1
        if expected_record is None:
            request = SaveWalk1Request(baseline, self._request_id)
            operation = self.history_service.save
        else:
            request = UpdateWalk1Request(
                baseline,
                expected_record,
                self._request_id,
            )
            operation = self.history_service.update
        self._task = "save"
        self._pending_save_revision = self._require_widget().draft_revision
        self.start_worker(self.analysis_name, request, operation)
        self._require_widget().show_save_busy()
        self.show_status("Saving Walk 1 baseline and preserving its source CSV")

    def request_history(self) -> None:
        if self.is_busy():
            return
        self._request_id += 1
        request = RangeWalkHistoryRequest(self._request_id)
        self._task = "history"
        self.start_worker(self.analysis_name, request, self.history_service.history)
        self._require_widget().show_history_busy()
        self.show_status("Loading saved Range-Walk baselines")

    def handle_success(self, result: object) -> bool:
        if isinstance(result, SavedWalk1Result):
            return self._handle_saved_baseline(result)
        if isinstance(result, RangeWalkHistoryResult):
            return self._handle_history(result)
        if not isinstance(result, RangeWalkPreviewResult):
            if not isinstance(result, RangeWalkCsvInspection):
                return False
            return self._handle_inspection(result)
        widget = self._require_widget()
        if (
            result.source_path != widget.source_path
            or result.request_id != self._request_id
        ):
            self.show_status("Stale Range-Walk marker preview was withheld")
            return True
        widget.show_result(result)
        self.show_status(
            f"Range-Walk marker preview ready — {result.direction_used}; "
            f"{len(result.markers)} candidate(s)"
        )
        return True

    def handle_failure(self, exc: Exception) -> None:
        operation = self._task
        if operation == "save":
            message = f"Unable to save Walk 1 baseline: {exc}"
            self._require_widget().show_persistence_error(message)
        elif operation == "history":
            message = f"Unable to load Range-Walk history: {exc}"
            self._require_widget().show_history_error(message)
        else:
            message = f"Unable to preview Range-Walk CSV: {exc}"
            self._require_widget().show_error(message, operation)
        self.show_status(message)

    def set_busy(self, busy: bool) -> None:
        if self.widget is not None:
            self.widget.set_busy(busy, self._task)
        if not busy:
            self._task = None

    def worker_finished(self, was_range_walk: bool) -> None:
        if not was_range_walk or self.is_busy() or self._pending_inspection is None:
            return
        source = self._pending_inspection
        self._pending_inspection = None
        if self._require_widget().source_path == source:
            self._start_inspection(source)

    def _start_inspection(self, source: Path) -> None:
        self._task = "inspect"
        request = RangeWalkInspectionRequest(source, self._request_id)
        self.start_worker(self.analysis_name, request, self.inspection_adapter)
        self._require_widget().show_inspection_busy()
        self.show_status(f"Reading Range-Walk CSV calibration clues — {source}")

    def _handle_inspection(self, result: RangeWalkCsvInspection) -> bool:
        widget = self._require_widget()
        if (
            result.source_path != widget.source_path
            or result.request_id != self._request_id
        ):
            self.show_status("Stale Range-Walk CSV inspection was withheld")
            return True
        widget.set_inspection(result)
        self.show_status(
            f"Range-Walk CSV ready — observed Ele {result.ele_min:g} to "
            f"{result.ele_max:g}"
        )
        return True

    def _handle_saved_baseline(self, result: SavedWalk1Result) -> bool:
        widget = self._require_widget()
        if (
            result.request_id != self._request_id
            or result.baseline.source_path != widget.source_path
        ):
            self.show_status(
                "Walk 1 was persisted, but its stale GUI result was withheld"
            )
            return True
        if self._pending_save_revision != widget.draft_revision:
            widget.retain_persisted_identity_for_newer_draft(
                result.baseline,
                result.record,
            )
            self.show_status(
                "Walk 1 was persisted; newer visible metadata remains unsaved"
            )
            return True
        widget.show_persisted_baseline(
            result.baseline,
            result.record,
            updated=result.updated,
        )
        self.show_status(f"Walk 1 baseline saved — {result.record.baseline_id}")
        return True

    def _handle_history(self, result: RangeWalkHistoryResult) -> bool:
        if result.request_id != self._request_id:
            self.show_status("Stale Range-Walk history result was withheld")
            return True
        self._require_widget().show_history(result.text)
        self.show_status(f"Loaded {len(result.records)} Range-Walk baseline(s)")
        return True

    def _source_error(self, message: str) -> None:
        self._require_widget().report.setPlainText(
            "Range-Walk CSV Selection Error\n"
            "==============================\n"
            f"{message}"
        )
        self.show_status(message)

    def _require_widget(self) -> RangeWalkPreviewWidget:
        assert self.widget is not None
        return self.widget
