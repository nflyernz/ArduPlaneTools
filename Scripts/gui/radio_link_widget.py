"""Focused Qt controls for BIN Radio Link and optional EdgeTX evidence."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .radio_link_adapter import (
    EdgeTxCandidateSet,
    EdgeTxGuiOverlay,
    EdgeTxOverlayRequest,
    RadioLinkCsvService,
    RadioLinkGuiResult,
    automatic_overlay_result,
)


class RadioLinkWidget(QWidget):
    """Aircraft evidence with a separately controlled transmitter overlay."""

    def __init__(
        self,
        analyse,
        discover,
        automatic,
        explicit,
        browse,
        parent=None,
    ):
        super().__init__(parent)
        self._result: RadioLinkGuiResult | None = None
        self._candidates: EdgeTxCandidateSet | None = None
        self._overlay: EdgeTxGuiOverlay | None = None
        self._view: str | None = None
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        notice = QLabel(
            "<b>Aircraft and transmitter logs</b><br>"
            "APT identifies aircraft failsafe events from the BIN log. An optional "
            "EdgeTX CSV adds transmitter information but does not change the "
            "aircraft results."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.bin_only_notice = notice

        report_controls = QHBoxLayout()
        report_controls.addStretch(1)
        self.summary_button = QPushButton("Show summary")
        self.summary_button.setObjectName("radioLinkSummaryButton")
        self.summary_button.clicked.connect(self.show_summary)
        report_controls.addWidget(self.summary_button)
        self.detail_button = QPushButton("Show detailed evidence")
        self.detail_button.setObjectName("radioLinkDetailButton")
        self.detail_button.clicked.connect(self.show_detail)
        report_controls.addWidget(self.detail_button)
        self.analyse_button = QPushButton("Analyse")
        self.analyse_button.setObjectName("radioLinkAnalyseButton")
        self.analyse_button.clicked.connect(analyse)
        report_controls.addWidget(self.analyse_button)
        layout.addLayout(report_controls)

        csv_source_controls = QHBoxLayout()
        csv_source_controls.addWidget(QLabel("Optional EdgeTX CSV:"))
        self.candidate_combo = QComboBox()
        self.candidate_combo.setObjectName("radioLinkCsvCandidateCombo")
        self.candidate_combo.setMinimumContentsLength(22)
        self.candidate_combo.currentIndexChanged.connect(
            self._show_candidate_hint
        )
        csv_source_controls.addWidget(self.candidate_combo, 1)
        layout.addLayout(csv_source_controls)

        csv_action_controls = QHBoxLayout()
        csv_action_controls.addStretch(1)
        self.discover_button = QPushButton("Discover nearby")
        self.discover_button.clicked.connect(discover)
        csv_action_controls.addWidget(self.discover_button)
        self.automatic_button = QPushButton("Auto pair")
        self.automatic_button.clicked.connect(automatic)
        csv_action_controls.addWidget(self.automatic_button)
        self.browse_button = QPushButton("Browse CSV…")
        self.browse_button.clicked.connect(browse)
        csv_action_controls.addWidget(self.browse_button)
        self.use_candidate_button = QPushButton("Use selected")
        self.use_candidate_button.clicked.connect(explicit)
        csv_action_controls.addWidget(self.use_candidate_button)
        self.remove_overlay_button = QPushButton("Remove CSV evidence")
        self.remove_overlay_button.clicked.connect(self.remove_overlay)
        csv_action_controls.addWidget(self.remove_overlay_button)
        layout.addLayout(csv_action_controls)

        diagnostic_group = QGroupBox()
        diagnostic_group.setObjectName("radioLinkCsvCandidateDiagnostic")
        diagnostic_layout = QVBoxLayout(diagnostic_group)
        diagnostic_layout.setContentsMargins(10, 8, 10, 8)
        self.candidate_hint = QLabel(
            "Analyse a BIN before selecting optional EdgeTX CSV evidence."
        )
        self.candidate_hint.setObjectName("radioLinkCsvCandidateHint")
        self.candidate_hint.setWordWrap(True)
        self.candidate_hint.setMinimumHeight(44)
        diagnostic_layout.addWidget(self.candidate_hint)
        layout.addWidget(diagnostic_group)
        self.candidate_diagnostic_group = diagnostic_group

        self.report = QPlainTextEdit()
        self.report.setObjectName("radio_link_report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setPlainText(
            "Radio Link\n\n"
            "Inspect radio-link quality and failsafe evidence.\n\n"
            "Select a BIN log above, then choose Analyse.\n\n"
            "The initial report shows a summary. Choose Show detailed evidence "
            "for the full findings."
        )
        layout.addWidget(self.report, 1)
        self._update_controls(False)

    @property
    def result(self) -> RadioLinkGuiResult | None:
        return self._result

    @property
    def candidates(self) -> EdgeTxCandidateSet | None:
        return self._candidates

    @property
    def overlay(self) -> EdgeTxGuiOverlay | None:
        return self._overlay

    @property
    def selected_candidate(self):
        index = self.candidate_combo.currentIndex()
        if self._candidates is None or index < 0:
            return None
        return self._candidates.candidates[index]

    def set_result(self, result: RadioLinkGuiResult) -> None:
        """Cache both BIN views and invalidate any earlier CSV state."""
        self._result = result
        self._view = "summary"
        self._clear_csv()
        self._render()
        self._update_controls(True)

    def clear_result(self, message: str) -> None:
        """Remove reports that no longer identify the selected source."""
        self._result = None
        self._view = None
        self._clear_csv()
        self.report.setPlainText(message)
        self._update_controls(not self._busy)

    def set_candidates(self, candidates: EdgeTxCandidateSet) -> None:
        """Show non-authoritative nearby candidate diagnostics."""
        self._candidates = candidates
        self.candidate_combo.clear()
        for candidate in candidates.candidates:
            self.candidate_combo.addItem(candidate.path.name)
        if candidates.candidates:
            self.candidate_combo.setCurrentIndex(0)
            self._show_candidate_hint()
        else:
            self.candidate_hint.setText("No nearby EdgeTX CSV candidates found.")
        self._update_controls(True)

    def set_overlay(self, overlay: EdgeTxGuiOverlay) -> None:
        """Attach formatted transmitter evidence without changing BIN evidence."""
        self._overlay = overlay
        self._render()
        self._update_controls(True)

    def remove_overlay(self) -> None:
        """Remove only the optional transmitter evidence."""
        self._overlay = None
        self._render()
        self._update_controls(self._result is not None)

    def show_summary(self) -> None:
        if self._result is not None:
            self._view = "summary"
            self._render()
            self._update_controls(True)

    def show_detail(self) -> None:
        if self._result is not None:
            self._view = "detail"
            self._render()
            self._update_controls(True)

    def show_csv_message(self, message: str) -> None:
        self.candidate_hint.setText(message)

    def render(self) -> None:
        """Restore cached evidence after MainWindow installs its busy message."""
        self._render()

    def set_busy(self, busy: bool, source_valid: bool) -> None:
        self._busy = busy
        self.analyse_button.setText("Analysing…" if busy else "Analyse")
        self._update_controls(not busy and source_valid)

    def _clear_csv(self) -> None:
        self._candidates = None
        self._overlay = None
        self.candidate_combo.clear()
        self.candidate_hint.setText(
            "Discover nearby EdgeTX CSV files or browse to one. Previewing a "
            "candidate does not establish pairing."
            if self._result is not None
            else "Analyse a BIN before selecting optional EdgeTX CSV evidence."
        )

    def _show_candidate_hint(self, _index: int | None = None) -> None:
        candidate = self.selected_candidate
        if candidate is not None:
            if not candidate.usable:
                classification = "Unusable candidate"
            elif candidate.automatic_eligible:
                classification = "Auto-eligible candidate"
            else:
                classification = "Explicit selection required"
            self.candidate_hint.setText(
                f"{classification}: {candidate.path.name}\n"
                f"{candidate.hint}\n"
                "Diagnostic preview only; pairing and alignment remain unverified."
            )

    def _render(self) -> None:
        if self._result is None:
            return
        aircraft = (
            self._result.detail if self._view == "detail" else self._result.summary
        )
        if self._overlay is None:
            self.report.setPlainText(aircraft)
            return
        self.report.setPlainText(
            f"{aircraft}\n\n"
            "OPTIONAL EDGETX CSV EVIDENCE\n"
            "============================\n"
            f"CSV: {self._overlay.csv_path.name}\n"
            f"{self._overlay.text}"
        )

    def _update_controls(self, source_valid: bool) -> None:
        has_result = self._result is not None
        available = not self._busy
        self.analyse_button.setEnabled(available and source_valid)
        self.summary_button.setEnabled(
            available and has_result and self._view != "summary"
        )
        self.detail_button.setEnabled(
            available and has_result and self._view != "detail"
        )
        self.discover_button.setEnabled(available and has_result)
        self.browse_button.setEnabled(available and has_result)
        self.automatic_button.setEnabled(
            available and has_result and self._candidates is not None
        )
        self.use_candidate_button.setEnabled(
            available and self.selected_candidate is not None
        )
        self.candidate_combo.setEnabled(
            available and self._candidates is not None
        )
        self.remove_overlay_button.setEnabled(
            available and self._overlay is not None
        )


class RadioLinkController:
    """Join Radio Link controls to MainWindow's shared worker lifecycle."""

    analysis_name = "Radio Link"

    def __init__(
        self,
        adapter,
        csv_service,
        start_worker,
        selected_source,
        selection_error,
        is_busy,
        show_error,
        show_status,
    ):
        self.adapter = adapter
        self.csv_service = csv_service or RadioLinkCsvService()
        self.start_worker = start_worker
        self.selected_source = selected_source
        self.selection_error = selection_error
        self.is_busy = is_busy
        self.show_error = show_error
        self.show_status = show_status
        self.widget: RadioLinkWidget | None = None
        self._task: str | None = None
        self._csv_request_id = 0

    def create_widget(self, parent=None) -> RadioLinkWidget:
        widget = RadioLinkWidget(
            self.request_analysis,
            self.request_discovery,
            self.request_automatic,
            self.request_selected,
            self.browse_csv,
            parent,
        )
        self.widget = widget
        return widget

    def request_analysis(self) -> None:
        if self.is_busy():
            return
        error = self.selection_error()
        if error is not None:
            self.show_error(self.analysis_name, error)
            return
        source = self.selected_source()
        assert source is not None
        self._csv_request_id += 1
        self._task = "bin"
        self._require_widget().clear_result(f"Radio Link\n\nAnalysing {source}…")
        self.start_worker(self.analysis_name, source, self.adapter)

    def request_discovery(self) -> None:
        if self.is_busy():
            return
        context = self._require_widget().result
        if context is None:
            return
        self._task = "discover"
        self._require_widget().show_csv_message("Discovering nearby CSV files…")
        self.start_worker(self.analysis_name, context, self.csv_service.discover)
        self._require_widget().render()

    def request_automatic(self) -> None:
        widget = self._require_widget()
        if self.is_busy() or widget.result is None or widget.candidates is None:
            return
        self._csv_request_id += 1
        outcome = automatic_overlay_result(
            widget.result,
            widget.candidates,
            self._csv_request_id,
        )
        if isinstance(outcome, str):
            message = outcome
            if outcome.startswith("Automatic pairing unavailable:"):
                message = (
                    "Automatic pairing unavailable: No CSV could be reliably "
                    "matched to this BIN. Use Discover nearby to find candidates, "
                    "then choose a CSV and click Use selected."
                )
                candidate = widget.selected_candidate
                if candidate is not None:
                    message += f"\nCandidate diagnostic: {candidate.hint}"
            widget.show_csv_message(message)
            self.show_status(message.replace("\n", " — "))
            return
        widget.set_overlay(outcome)
        widget.show_csv_message(f"Using automatically paired {outcome.csv_path.name}.")
        self.show_status("Optional EdgeTX evidence displayed")

    def request_selected(self) -> None:
        widget = self._require_widget()
        candidate = widget.selected_candidate
        if self.is_busy() or widget.result is None or candidate is None:
            return
        self._start_explicit(candidate.path, candidate.session)

    def browse_csv(self) -> None:
        widget = self._require_widget()
        if self.is_busy() or widget.result is None:
            return
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            widget,
            "Select EdgeTX CSV telemetry",
            str(widget.result.source_path.parent),
            "EdgeTX CSV files (*.csv *.CSV)",
        )
        if file_name:
            self._start_explicit(Path(file_name).expanduser().resolve())

    def source_changed(self, source: Path) -> None:
        widget = self._require_widget()
        result = widget.result
        if result is not None and result.source_path != source:
            self._csv_request_id += 1
            widget.clear_result(
                "Radio Link\n\n"
                "The selected BIN changed. Choose Analyse to load its evidence."
            )

    def handle_success(self, result: object) -> bool:
        widget = self._require_widget()
        selected = self.selected_source()
        if isinstance(result, RadioLinkGuiResult):
            if result.source_path != selected:
                widget.clear_result(
                    "Radio Link\n\n"
                    "The selected BIN changed while analysis was running. "
                    "The previous result was not displayed."
                )
                self.show_status(
                    "Radio Link result withheld after BIN selection changed"
                )
                return True
            widget.set_result(result)
            self.show_status(
                "Radio Link summary ready — optional EdgeTX evidence is available"
            )
            return True
        if isinstance(result, EdgeTxCandidateSet):
            if result.source_path != selected or widget.result is None:
                self.show_status("Stale EdgeTX candidate results were withheld")
                return True
            widget.set_candidates(result)
            self.show_status(
                f"Found {len(result.candidates)} nearby EdgeTX CSV candidate(s)"
            )
            return True
        if isinstance(result, EdgeTxGuiOverlay):
            if (
                result.source_path != selected
                or widget.result is None
                or result.request_id != self._csv_request_id
            ):
                self.show_status("Stale EdgeTX overlay was withheld")
                return True
            widget.set_overlay(result)
            widget.show_csv_message(
                f"Using selected CSV: {result.csv_path.name}.\n"
                "Manual selection does not verify pairing or alignment."
            )
            self.show_status("Optional EdgeTX evidence displayed")
            return True
        return False

    def handle_failure(self, exc: Exception) -> None:
        if self._task == "bin":
            self._require_widget().clear_result("Radio Link analysis failed.")
            self.show_error(self.analysis_name, self._bin_error_message(exc))
            return
        message = f"Unable to use EdgeTX CSV: {exc}"
        self._require_widget().show_csv_message(message)
        self._require_widget().render()
        self.show_status(message)

    def set_busy(self, busy: bool) -> None:
        if self.widget is not None:
            self.widget.set_busy(busy, self.selection_error() is None)
        if not busy:
            self._task = None

    def _start_explicit(self, path: Path, session=None) -> None:
        widget = self._require_widget()
        context = widget.result
        if context is None:
            return
        self._csv_request_id += 1
        request = EdgeTxOverlayRequest(
            context,
            path,
            self._csv_request_id,
            session,
        )
        self._task = "explicit"
        widget.show_csv_message(f"Reading {path.name}…")
        self.start_worker(self.analysis_name, request, self.csv_service.explicit)
        widget.render()

    @staticmethod
    def _bin_error_message(exc: Exception) -> str:
        from core.log_reader import UnsupportedFirmwareError

        if isinstance(exc, UnsupportedFirmwareError):
            return f"Unsupported firmware.\n{exc}"
        if isinstance(exc, OSError):
            return f"Unable to read log: {exc}"
        return f"Radio Link analysis failed unexpectedly: {exc}"

    def _require_widget(self) -> RadioLinkWidget:
        assert self.widget is not None
        return self.widget
