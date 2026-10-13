"""Focused Qt controls for aircraft-BIN Radio Link evidence."""

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .radio_link_adapter import RadioLinkGuiResult


class RadioLinkWidget(QWidget):
    """Explicit analysis and cached summary/detail report views."""

    def __init__(self, analyse, parent=None):
        super().__init__(parent)
        self._result: RadioLinkGuiResult | None = None
        self._view: str | None = None
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        notice = QLabel(
            "<b>Aircraft BIN evidence only</b><br>"
            "Optional EdgeTX CSV pairing and RF overlay are not yet supported "
            "in the GUI. The CLI retains that optional workflow."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.bin_only_notice = notice

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.summary_button = QPushButton("Show summary")
        self.summary_button.setObjectName("radioLinkSummaryButton")
        self.summary_button.clicked.connect(self.show_summary)
        controls.addWidget(self.summary_button)
        self.detail_button = QPushButton("Show detailed evidence")
        self.detail_button.setObjectName("radioLinkDetailButton")
        self.detail_button.clicked.connect(self.show_detail)
        controls.addWidget(self.detail_button)
        self.analyse_button = QPushButton("Analyse")
        self.analyse_button.setObjectName("radioLinkAnalyseButton")
        self.analyse_button.clicked.connect(analyse)
        controls.addWidget(self.analyse_button)
        layout.addLayout(controls)

        self.report = QPlainTextEdit()
        self.report.setObjectName("radio_link_report")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setPlainText(
            "Radio Link\n\n"
            "Select a BIN log above, then choose Analyse.\n\n"
            "The initial result is the summary view."
        )
        layout.addWidget(self.report, 1)
        self._update_controls(False, False)

    @property
    def result(self) -> RadioLinkGuiResult | None:
        return self._result

    def set_result(self, result: RadioLinkGuiResult) -> None:
        """Cache both views and initially display the existing summary."""
        self._result = result
        self._view = "summary"
        self.report.setPlainText(result.summary)
        self._update_controls(True, True)

    def clear_result(self, message: str) -> None:
        """Remove reports that no longer identify the selected source."""
        self._result = None
        self._view = None
        self.report.setPlainText(message)
        self._update_controls(not self._busy, False)

    def show_summary(self) -> None:
        """Show the cached summary without rerunning analysis."""
        if self._result is not None:
            self._view = "summary"
            self.report.setPlainText(self._result.summary)
            self._update_controls(not self._busy, True)

    def show_detail(self) -> None:
        """Show cached detailed aircraft evidence without rerunning analysis."""
        if self._result is not None:
            self._view = "detail"
            self.report.setPlainText(self._result.detail)
            self._update_controls(not self._busy, True)

    def set_busy(self, busy: bool, source_valid: bool) -> None:
        """Reflect the shared worker state without discarding cached evidence."""
        self._busy = busy
        self.analyse_button.setText("Analysing…" if busy else "Analyse")
        self._update_controls(not busy and source_valid, self._result is not None)

    def _update_controls(self, can_analyse: bool, has_result: bool) -> None:
        self.analyse_button.setEnabled(can_analyse)
        self.summary_button.setEnabled(
            has_result and not self._busy and self._view != "summary"
        )
        self.detail_button.setEnabled(
            has_result and not self._busy and self._view != "detail"
        )


class RadioLinkController:
    """Join Radio Link controls to MainWindow's existing worker lifecycle."""

    analysis_name = "Radio Link"

    def __init__(
        self,
        adapter,
        start_worker,
        selected_source,
        selection_error,
        is_busy,
        show_error,
        show_status,
    ):
        self.adapter = adapter
        self.start_worker = start_worker
        self.selected_source = selected_source
        self.selection_error = selection_error
        self.is_busy = is_busy
        self.show_error = show_error
        self.show_status = show_status
        self.widget: RadioLinkWidget | None = None

    def create_widget(self, parent=None) -> RadioLinkWidget:
        widget = RadioLinkWidget(self.request_analysis, parent)
        self.widget = widget
        return widget

    def request_analysis(self) -> None:
        """Validate and run exactly one BIN analysis operation."""
        if self.is_busy():
            return
        error = self.selection_error()
        if error is not None:
            self.show_error(self.analysis_name, error)
            return
        source = self.selected_source()
        assert source is not None
        self._require_widget().clear_result(
            f"Radio Link\n\nAnalysing {source}…"
        )
        self.start_worker(self.analysis_name, source, self.adapter)

    def source_changed(self, source: Path) -> None:
        """Invalidate cached evidence when it no longer matches selection."""
        widget = self._require_widget()
        result = widget.result
        if result is not None and result.source_path != source:
            widget.clear_result(
                "Radio Link\n\n"
                "The selected BIN changed. Choose Analyse to load its evidence."
            )

    def handle_success(self, result: object) -> bool:
        """Accept only a correctly sourced result from the Radio Link adapter."""
        if not isinstance(result, RadioLinkGuiResult):
            return False
        if result.source_path != self.selected_source():
            self._require_widget().clear_result(
                "Radio Link\n\n"
                "The selected BIN changed while analysis was running. "
                "The previous result was not displayed."
            )
            self.show_status("Radio Link result withheld after BIN selection changed")
            return True
        self._require_widget().set_result(result)
        self.show_status("Radio Link summary ready — detailed evidence is available")
        return True

    def handle_failure(self, exc: Exception) -> None:
        self._require_widget().clear_result("Radio Link analysis failed.")
        self.show_error(self.analysis_name, self._error_message(exc))

    def set_busy(self, busy: bool) -> None:
        if self.widget is not None:
            self.widget.set_busy(busy, self.selection_error() is None)

    @staticmethod
    def _error_message(exc: Exception) -> str:
        from core.log_reader import UnsupportedFirmwareError

        if isinstance(exc, UnsupportedFirmwareError):
            return f"Unsupported firmware.\n{exc}"
        if isinstance(exc, OSError):
            return f"Unable to read log: {exc}"
        return f"Radio Link analysis failed unexpectedly: {exc}"

    def _require_widget(self) -> RadioLinkWidget:
        assert self.widget is not None
        return self.widget
