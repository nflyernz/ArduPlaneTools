"""Focused Qt controls for Range-Walk CSV marker preview."""

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .range_walk_adapter import (
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    analyse_range_walk_preview,
)


class RangeWalkPreviewWidget(QWidget):
    """One CSV source, calibration inputs and marker-candidate report."""

    def __init__(self, choose_source, detect, parent=None):
        super().__init__(parent)
        self._source_path: Path | None = None
        self._busy = False
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

        calibration_group = QGroupBox("Elevator marker calibration")
        calibration_layout = QFormLayout(calibration_group)
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
        calibration_layout.addRow(
            "Calibrated full elevator-down Ele:", self.down_edit
        )
        calibration_layout.addRow("Calibrated neutral Ele:", self.neutral_edit)
        calibration_layout.addRow(
            "Near-down threshold:", self.near_down_edit
        )
        layout.addWidget(calibration_group)

        action_layout = QHBoxLayout()
        action_layout.addStretch(1)
        self.detect_button = QPushButton("Detect markers")
        self.detect_button.setObjectName("rangeWalkDetectMarkersButton")
        self.detect_button.clicked.connect(detect)
        action_layout.addWidget(self.detect_button)
        layout.addLayout(action_layout)

        self.report = QPlainTextEdit()
        self.report.setObjectName("range_walk_preview_report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            "Choose one EdgeTX CSV and enter its local elevator calibration."
        )
        layout.addWidget(self.report, 1)
        self._update_controls()

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    def set_source(self, path: Path) -> None:
        self._source_path = path
        self.source_path_edit.setText(str(path))
        self.source_path_edit.setToolTip(str(path))
        self.source_path_edit.setCursorPosition(0)
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Selected: {path}\n\n"
            "Enter calibration and choose Detect markers."
        )
        self._update_controls()

    def calibration(self) -> tuple[str, str, str]:
        return (
            self.down_edit.text(),
            self.neutral_edit.text(),
            self.near_down_edit.text(),
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.detect_button.setText("Detecting…" if busy else "Detect markers")
        self._update_controls()

    def show_busy(self) -> None:
        assert self._source_path is not None
        self.report.setPlainText(
            "Range-Walk CSV / marker preview\n\n"
            f"Reading {self._source_path} and detecting markers…\n\n"
            "The GUI remains available; no progress percentage is available."
        )

    def _update_controls(self) -> None:
        available = not self._busy
        self.choose_button.setEnabled(available)
        self.detect_button.setEnabled(available and self._source_path is not None)
        for field in (self.down_edit, self.neutral_edit, self.near_down_edit):
            field.setEnabled(available)


class RangeWalkPreviewController:
    """Run marker previews through MainWindow's shared one-shot worker."""

    analysis_name = "Range-Walk Comparison"

    def __init__(self, adapter, start_worker, is_busy, show_status):
        self.adapter = adapter or analyse_range_walk_preview
        self.start_worker = start_worker
        self.is_busy = is_busy
        self.show_status = show_status
        self.widget: RangeWalkPreviewWidget | None = None
        self._request_id = 0

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
        self.start_worker(self.analysis_name, request, self.adapter)
        widget.show_busy()
        self.show_status(f"Detecting marker candidates — {widget.source_path}")

    def handle_success(self, result: object) -> bool:
        if not isinstance(result, RangeWalkPreviewResult):
            return False
        widget = self._require_widget()
        if (
            result.source_path != widget.source_path
            or result.request_id != self._request_id
        ):
            self.show_status("Stale Range-Walk marker preview was withheld")
            return True
        widget.report.setPlainText(result.text)
        self.show_status(
            f"Range-Walk marker preview ready — {len(result.markers)} candidate(s)"
        )
        return True

    def handle_failure(self, exc: Exception) -> None:
        message = f"Unable to preview Range-Walk CSV: {exc}"
        self._require_widget().report.setPlainText(
            "Range-Walk CSV Preview Error\n"
            "============================\n"
            f"{message}"
        )
        self.show_status(message)

    def set_busy(self, busy: bool) -> None:
        if self.widget is not None:
            self.widget.set_busy(busy)

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
