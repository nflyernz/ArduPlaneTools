"""Focused Qt controls for Range-Walk CSV marker preview."""

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .range_walk_adapter import (
    RangeWalkCsvInspection,
    RangeWalkInspectionRequest,
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    analyse_range_walk_preview,
    inspect_range_walk_csv,
    marker_calibration,
)


class RangeWalkPreviewWidget(QWidget):
    """One CSV source, calibration inputs and marker-candidate report."""

    def __init__(self, choose_source, detect, parent=None):
        super().__init__(parent)
        self._source_path: Path | None = None
        self._inspection: RangeWalkCsvInspection | None = None
        self._outcome = ""
        self._busy = False
        self._busy_task: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        notice = QLabel(
            "<b>CSV/marker preview only — comparison not yet connected</b><br>"
            "Candidates are calibrated elevator holds, not confirmed landmarks. "
            "The shared aircraft BIN selection does not apply."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
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
        layout.addLayout(source_layout)

        calibration_group = QGroupBox("Suggested elevator calibration")
        calibration_layout = QVBoxLayout(calibration_group)
        guidance = QLabel(
            "Ele is the transmitter channel value recorded in this EdgeTX CSV. "
            "The CSV can suggest sustained neutral and endpoint values, but it "
            "cannot determine which direction is elevator-down. Confirm the "
            "direction against the deliberate recorded holds."
        )
        guidance.setWordWrap(True)
        calibration_layout.addWidget(guidance)
        self.calibration_guidance = guidance

        direction_layout = QHBoxLayout()
        direction_layout.addWidget(QLabel("Elevator-down direction:"))
        self.higher_direction = QRadioButton("Higher Ele value (+)")
        self.higher_direction.setObjectName("rangeWalkHigherDirection")
        self.lower_direction = QRadioButton("Lower Ele value (−)")
        self.lower_direction.setObjectName("rangeWalkLowerDirection")
        self.direction_group = QButtonGroup(self)
        self.direction_group.addButton(self.higher_direction)
        self.direction_group.addButton(self.lower_direction)
        direction_layout.addWidget(self.higher_direction)
        direction_layout.addWidget(self.lower_direction)
        direction_layout.addStretch(1)
        calibration_layout.addLayout(direction_layout)
        self.suggestion_label = QLabel("Choose a CSV to obtain calibration suggestions.")
        self.suggestion_label.setObjectName("rangeWalkCalibrationSuggestion")
        self.suggestion_label.setWordWrap(True)
        calibration_layout.addWidget(self.suggestion_label)
        self.confirm_calibration = QCheckBox(
            "I confirm this calibration matches the recorded elevator-down holds."
        )
        self.confirm_calibration.setObjectName("rangeWalkConfirmCalibration")
        calibration_layout.addWidget(self.confirm_calibration)
        layout.addWidget(calibration_group)

        manual_group = QGroupBox("Advanced / Manual calibration")
        manual_group.setCheckable(True)
        manual_group.setChecked(False)
        manual_layout = QFormLayout(manual_group)
        self.down_edit = QLineEdit()
        self.down_edit.setObjectName("rangeWalkDownCalibration")
        self.down_edit.setPlaceholderText("Example: 900 or -900")
        self.neutral_edit = QLineEdit()
        self.neutral_edit.setObjectName("rangeWalkNeutralCalibration")
        self.neutral_edit.setPlaceholderText("Example: 0")
        self.near_down_edit = QLineEdit()
        self.near_down_edit.setObjectName("rangeWalkNearDownCalibration")
        self.near_down_edit.setPlaceholderText(
            "Optional — blank uses 87.5% of calibrated span"
        )
        manual_layout.addRow(
            "Calibrated full elevator-down Ele:", self.down_edit
        )
        manual_layout.addRow("Calibrated neutral Ele:", self.neutral_edit)
        manual_layout.addRow(
            "Near-down threshold:", self.near_down_edit
        )
        threshold_note = QLabel(
            "Optional: blank uses 87.5% of the calibrated neutral-to-down span."
        )
        threshold_note.setWordWrap(True)
        manual_layout.addRow(threshold_note)
        layout.addWidget(manual_group)
        self.manual_group = manual_group

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.detect_button = QPushButton("Detect markers")
        self.detect_button.setObjectName("rangeWalkDetectMarkersButton")
        self.detect_button.clicked.connect(detect)
        action_layout.addWidget(self.detect_button)
        layout.addLayout(action_layout)

        self.state_label = QLabel()
        self.state_label.setObjectName("rangeWalkPreviewState")
        self.state_label.setWordWrap(True)
        self.state_label.setMinimumHeight(38)
        layout.addWidget(self.state_label)

        self.report = QPlainTextEdit()
        self.report.setObjectName("range_walk_preview_report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            "Choose one EdgeTX CSV and enter its local elevator calibration."
        )
        layout.addWidget(self.report, 1)
        for field in (self.down_edit, self.neutral_edit, self.near_down_edit):
            field.textChanged.connect(self._calibration_changed)
        self.higher_direction.toggled.connect(self._direction_changed)
        self.lower_direction.toggled.connect(self._direction_changed)
        self.manual_group.toggled.connect(self._manual_changed)
        self.confirm_calibration.toggled.connect(self._update_controls)
        self._update_controls()

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    def set_source(self, path: Path) -> None:
        self._source_path = path
        self._inspection = None
        self._outcome = ""
        self._clear_direction()
        self.confirm_calibration.setChecked(False)
        self.manual_group.setChecked(False)
        self.source_path_edit.setText(str(path))
        self.source_path_edit.setToolTip(str(path))
        self.source_path_edit.setCursorPosition(0)
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Selected: {path}\n\n"
            "Enter calibration and choose Detect markers."
        )
        self._update_controls()

    def set_inspection(self, inspection: RangeWalkCsvInspection) -> None:
        self._inspection = inspection
        self._outcome = ""
        self.confirm_calibration.setChecked(False)
        suggestions = inspection.calibration
        self.report.setPlainText(
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
        self._update_suggestion_label()
        self._update_controls()

    def calibration(self) -> tuple[str, str, str]:
        if not self.manual_group.isChecked():
            suggestions = self._inspection.calibration if self._inspection else None
            endpoint = None
            if suggestions is not None:
                endpoint = (
                    suggestions.high
                    if self.higher_direction.isChecked()
                    else suggestions.low if self.lower_direction.isChecked() else None
                )
            if suggestions is None or suggestions.neutral is None or endpoint is None:
                return "", "", ""
            return f"{endpoint:g}", f"{suggestions.neutral:g}", ""
        return (
            self.down_edit.text(),
            self.neutral_edit.text(),
            self.near_down_edit.text(),
        )

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
            "No elevator direction or calibration value will be assigned."
        )

    def show_busy(self) -> None:
        assert self._source_path is not None
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Reading {self._source_path} and detecting markers…\n\n"
            "The GUI remains available; no progress percentage is available."
        )

    def show_result(self, result: RangeWalkPreviewResult) -> None:
        self._outcome = (
            f"Detection completed — {len(result.markers)} marker candidate(s)."
        )
        self.report.setPlainText(result.text)
        self._update_controls()

    def show_error(self, message: str, task: str | None) -> None:
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

    def _calibration_changed(self) -> None:
        self._outcome = ""
        self.confirm_calibration.setChecked(False)
        self._update_controls()

    def _direction_changed(self) -> None:
        self._outcome = ""
        self.confirm_calibration.setChecked(False)
        self._update_suggestion_label()
        self._update_controls()

    def _manual_changed(self) -> None:
        self._outcome = ""
        self.confirm_calibration.setChecked(False)
        self._update_suggestion_label()
        self._update_controls()

    def _clear_direction(self) -> None:
        self.direction_group.setExclusive(False)
        self.higher_direction.setChecked(False)
        self.lower_direction.setChecked(False)
        self.direction_group.setExclusive(True)

    def _update_suggestion_label(self) -> None:
        if self.manual_group.isChecked():
            text = "Manual calibration is active. Enter the confirmed values below."
        elif self._inspection is None:
            text = "Choose a CSV to obtain calibration suggestions."
        else:
            suggestions = self._inspection.calibration
            neutral = _format_suggestion(suggestions.neutral)
            if self.higher_direction.isChecked():
                endpoint = _format_suggestion(suggestions.high)
                direction = "higher"
            elif self.lower_direction.isChecked():
                endpoint = _format_suggestion(suggestions.low)
                direction = "lower"
            else:
                endpoint = "choose a direction"
                direction = "selected"
            text = (
                f"Suggested neutral: {neutral}. Suggested full-down for the "
                f"{direction} direction: {endpoint}. {suggestions.explanation} "
                "Suggestions do not verify control direction."
            )
        self.suggestion_label.setText(text)

    def _calibration_error(self) -> str | None:
        try:
            marker_calibration(*self.calibration())
        except ValueError as exc:
            return str(exc)
        return None

    def _update_controls(self) -> None:
        available = not self._busy
        self.choose_button.setEnabled(available)
        calibration_error = self._calibration_error()
        proposed = self._inspection is not None and calibration_error is None
        confirmed = proposed and self.confirm_calibration.isChecked()
        self.detect_button.setEnabled(available and confirmed)
        self.higher_direction.setEnabled(available and self._inspection is not None)
        self.lower_direction.setEnabled(available and self._inspection is not None)
        self.manual_group.setEnabled(available and self._inspection is not None)
        self.confirm_calibration.setEnabled(available and proposed)
        for field in (self.down_edit, self.neutral_edit, self.near_down_edit):
            field.setEnabled(available and self.manual_group.isChecked())
        if self._busy:
            state = (
                "Reading selected CSV and observed Ele range…"
                if self._busy_task == "inspect"
                else "Detection running…"
            )
        elif self._source_path is None:
            state = "No CSV selected — choose one EdgeTX transmitter log."
        elif self._outcome:
            state = self._outcome
        elif self._inspection is None:
            state = "CSV selected — observed Ele range is not yet available."
        elif calibration_error is not None:
            state = (
                f"CSV selected — calibration unavailable or invalid: {calibration_error}. "
                "Choose a supported direction or use Advanced / Manual calibration."
            )
        elif not self.confirm_calibration.isChecked():
            state = "Calibration proposed — confirm it before detecting markers."
        else:
            state = "Ready to detect marker candidates."
        self.state_label.setText(state)


def _format_suggestion(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value:g}"


class RangeWalkPreviewController:
    """Run marker previews through MainWindow's shared one-shot worker."""

    analysis_name = "Range-Walk Comparison"

    def __init__(
        self,
        adapter,
        inspection_adapter,
        start_worker,
        is_busy,
        show_status,
    ):
        self.adapter = adapter or analyse_range_walk_preview
        self.inspection_adapter = inspection_adapter or inspect_range_walk_csv
        self.start_worker = start_worker
        self.is_busy = is_busy
        self.show_status = show_status
        self.widget: RangeWalkPreviewWidget | None = None
        self._request_id = 0
        self._task: str | None = None
        self._pending_inspection: Path | None = None

    def create_widget(self, parent=None) -> RangeWalkPreviewWidget:
        widget = RangeWalkPreviewWidget(
            self.choose_source,
            self.request_preview,
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
        down, neutral, near_down = widget.calibration()
        request = RangeWalkPreviewRequest(
            widget.source_path,
            down,
            neutral,
            near_down,
            self._request_id,
        )
        self._task = "detect"
        self.start_worker(self.analysis_name, request, self.adapter)
        widget.show_busy()
        self.show_status(f"Detecting marker candidates — {widget.source_path}")

    def handle_success(self, result: object) -> bool:
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
            f"Range-Walk marker preview ready — {len(result.markers)} candidate(s)"
        )
        return True

    def handle_failure(self, exc: Exception) -> None:
        message = f"Unable to preview Range-Walk CSV: {exc}"
        self._require_widget().show_error(message, self._task)
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
