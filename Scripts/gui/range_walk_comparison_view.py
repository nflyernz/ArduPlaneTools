"""Focused read-only Qt view for saved Range-Walk comparisons."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.range_walk_history import StoredAdditionalWalk, StoredWalk1Baseline

from .range_walk_comparison_adapter import RangeWalkComparisonResult


class RangeWalkComparisonView(QWidget):
    """Selectors, section evidence, plots and metadata for saved walks."""

    def __init__(self, compare, parent=None):
        super().__init__(parent)
        self._compare = compare
        self._walks: dict[str, StoredAdditionalWalk] = {}
        self._plot_pixmaps: list[QPixmap] = []
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        notice = QLabel(
            "Select a saved Walk 1 and one associated later walk. Comparisons "
            "are reconstructed read-only from checksum-verified managed CSVs."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        selectors = QFormLayout()
        self.baseline_combo = QComboBox()
        self.baseline_combo.setObjectName("rangeWalkHistoryBaseline")
        selectors.addRow("Walk 1 baseline:", self.baseline_combo)
        self.walk_combo = QComboBox()
        self.walk_combo.setObjectName("rangeWalkHistoryComparisonWalk")
        selectors.addRow("Comparison walk:", self.walk_combo)
        layout.addLayout(selectors)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.compare_button = QPushButton("Compare selected walks")
        self.compare_button.setObjectName("rangeWalkCompareHistoryButton")
        if compare is not None:
            self.compare_button.clicked.connect(compare)
        actions.addWidget(self.compare_button)
        layout.addLayout(actions)
        self.state_label = QLabel(
            "Load history, then select a baseline and associated walk."
        )
        self.state_label.setObjectName("rangeWalkComparisonState")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("rangeWalkHistoryTabs")
        comparison_page = QWidget()
        comparison_layout = QVBoxLayout(comparison_page)
        self.qualification = QLabel("No saved RF comparison has been run yet.")
        self.qualification.setObjectName("rangeWalkComparisonQualification")
        self.qualification.setWordWrap(True)
        comparison_layout.addWidget(self.qualification)
        self.table = QTableWidget(0, 9)
        self.table.setObjectName("rangeWalkComparisonTable")
        self.table.setHorizontalHeaderLabels(
            (
                "Section",
                "Walk",
                "1RSS median",
                "1RSS P10",
                "RQly P10",
                "RSNR median",
                "Usable coverage",
                "Longest unavailable",
                "Evidence status",
            )
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        comparison_layout.addWidget(self.table, 1)
        self.tabs.addTab(comparison_page, "Section comparison")
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setObjectName("rangeWalkPlotTabs")
        self.tabs.addTab(self.plot_tabs, "Plots")
        self.details = QPlainTextEdit()
        self.details.setObjectName("rangeWalkHistoryReport")
        self.details.setReadOnly(True)
        self.details.setPlainText(
            "Range-Walk History & Comparison\n\nOpen this page to load history.\n"
            "Select two saved walks to calculate RF evidence."
        )
        self.tabs.addTab(self.details, "Details & metadata")
        layout.addWidget(self.tabs, 1)
        self.baseline_combo.currentIndexChanged.connect(
            lambda _index: self._baseline_changed()
        )
        self.walk_combo.currentIndexChanged.connect(
            lambda _index: self._walk_changed()
        )
        self.set_busy(False)

    def selected_ids(self) -> tuple[str | None, str | None]:
        return self.baseline_combo.currentData(), self.walk_combo.currentData()

    def show_history(self, text, records, walks) -> None:
        selected_baseline, selected_walk = self.selected_ids()
        self._walks = {walk.walk_id: walk for walk in walks}
        self.baseline_combo.blockSignals(True)
        self.baseline_combo.clear()
        self.baseline_combo.addItem("Select saved baseline…", None)
        for record in records:
            self.baseline_combo.addItem(
                f"{record.label} — {record.baseline_id}", record.baseline_id
            )
        index = self.baseline_combo.findData(selected_baseline)
        if selected_baseline is None and len(records) == 1:
            index = 1
        elif index < 0 and len(records) == 1:
            index = 1
        self.baseline_combo.setCurrentIndex(max(0, index))
        self.baseline_combo.blockSignals(False)
        self._baseline_changed(selected_walk)
        self.details.setPlainText(text)

    def show_history_busy(self) -> None:
        self.state_label.setText("Loading and validating saved Range-Walk history…")

    def show_history_error(self, message: str) -> None:
        self._walks = {}
        for combo in (self.baseline_combo, self.walk_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("History unavailable", None)
            combo.blockSignals(False)
        self.clear_comparison(message)
        self.details.setPlainText(
            "Range-Walk History Error\n"
            "========================\n"
            f"{message}\n\nNo comparison was calculated."
        )

    def show_comparison_busy(self) -> None:
        self.clear_comparison(
            "Loading managed CSVs and calculating Range-Walk RF evidence…"
        )

    def show_comparison_error(self, message: str) -> None:
        self.clear_comparison(message)
        self.details.setPlainText(
            "Range-Walk Comparison Error\n"
            "===========================\n"
            f"{message}\n\nNo RF values or plots were inferred."
        )

    def show_comparison(self, result: RangeWalkComparisonResult) -> None:
        self.state_label.setText(
            f"Comparison ready — {result.baseline.label} / {result.walk.label}."
        )
        self.qualification.setText(result.qualification)
        self.table.setRowCount(len(result.rows))
        for row_index, row in enumerate(result.rows):
            evidence = row.evidence
            values = (
                row.section,
                row.walk,
                _metric(evidence, "median_values", "1RSS(dB)", " dBm"),
                _metric(evidence, "p10_values", "1RSS(dB)", " dBm"),
                _metric(evidence, "p10_values", "RQly(%)", "%"),
                _metric(evidence, "median_values", "RSNR(dB)", " dB"),
                _coverage(evidence),
                f"{evidence.longest_unavailable_s:.1f} s"
                if evidence is not None
                else "Unavailable",
                row.status,
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
        self.table.resizeRowsToContents()
        self._clear_plots()
        for plot in result.plots:
            image = QImage.fromData(plot.data, "PNG")
            if image.isNull():
                continue
            pixmap = QPixmap.fromImage(image)
            self._plot_pixmaps.append(pixmap)
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(
                pixmap.scaled(
                    1050,
                    650,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(label)
            self.plot_tabs.addTab(scroll, plot.title)
        self.details.setPlainText(result.details)
        self.tabs.setCurrentIndex(0)

    def clear_comparison(self, message: str) -> None:
        self.state_label.setText(message)
        self.qualification.setText("No saved RF comparison is currently displayed.")
        self.table.setRowCount(0)
        self._clear_plots()

    def set_busy(self, busy: bool, task: str | None = None) -> None:
        self._busy = busy
        available = not busy
        self.baseline_combo.setEnabled(available)
        self.walk_combo.setEnabled(
            available and self.baseline_combo.currentData() is not None
        )
        self.compare_button.setEnabled(
            available
            and self.baseline_combo.currentData() is not None
            and self.walk_combo.currentData() is not None
        )
        self.compare_button.setText(
            "Calculating…" if busy and task == "compare" else "Compare selected walks"
        )

    def _baseline_changed(self, previous_walk=None) -> None:
        previous_walk = (
            self.walk_combo.currentData()
            if previous_walk is None
            else previous_walk
        )
        baseline_id = self.baseline_combo.currentData()
        self.walk_combo.blockSignals(True)
        self.walk_combo.clear()
        self.walk_combo.addItem("Select associated walk…", None)
        associated = [
            walk for walk in self._walks.values()
            if walk.parent_baseline_id == baseline_id
        ]
        for walk in associated:
            self.walk_combo.addItem(f"{walk.label} — {walk.walk_id}", walk.walk_id)
        index = self.walk_combo.findData(previous_walk)
        if previous_walk is None and len(associated) == 1:
            index = 1
        elif index < 0 and len(associated) == 1:
            index = 1
        self.walk_combo.setCurrentIndex(max(0, index))
        self.walk_combo.blockSignals(False)
        self.clear_comparison(
            "Select an associated walk to calculate the four RF sections."
            if associated
            else "This saved baseline has no associated comparison walks."
        )
        self.set_busy(self._busy)

    def _walk_changed(self) -> None:
        self.clear_comparison(
            "Ready to compare the selected saved walks."
            if self.walk_combo.currentData() is not None
            else "Select an associated walk to calculate the four RF sections."
        )
        self.set_busy(self._busy)

    def _clear_plots(self) -> None:
        self._plot_pixmaps.clear()
        while self.plot_tabs.count():
            page = self.plot_tabs.widget(0)
            self.plot_tabs.removeTab(0)
            page.deleteLater()


def _metric(evidence, collection: str, field: str, unit: str) -> str:
    if evidence is None:
        return "Incomplete"
    value = getattr(evidence, collection)[field]
    return "Unavailable" if value is None else f"{value:.1f}{unit}"


def _coverage(evidence) -> str:
    if evidence is None:
        return "Incomplete"
    count = evidence.usable_counts["1RSS(dB)"]
    return (
        f"{count}/{evidence.row_count} rows; "
        f"{100 * evidence.rssi_coverage:.0f}% observed time"
    )
