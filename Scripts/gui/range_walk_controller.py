"""Background controller for the Range-Walk GUI workflow."""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from core.range_walk_history import StoredWalk1Baseline

from .range_walk_adapter import (
    AdditionalWalk,
    RangeWalkCsvInspection,
    RangeWalkInspectionRequest,
    RangeWalkPreviewRequest,
    RangeWalkPreviewResult,
    Walk1Baseline,
    analyse_range_walk_preview,
    inspect_range_walk_csv,
)
from .range_walk_history_adapter import (
    RangeWalkHistoryRequest,
    RangeWalkHistoryResult,
    RangeWalkHistoryService,
    SaveAdditionalWalkRequest,
    SaveWalk1Request,
    SavedAdditionalWalkResult,
    SavedWalk1Result,
    UpdateWalk1Request,
)
from .range_walk_comparison_adapter import (
    RangeWalkComparisonRequest,
    RangeWalkComparisonResult,
)
from .range_walk_widget import RangeWalkPreviewWidget


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
            self.request_comparison,
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
        baseline: Walk1Baseline | AdditionalWalk,
        expected_record: StoredWalk1Baseline | None,
    ) -> None:
        if self.is_busy():
            return
        self._request_id += 1
        if isinstance(baseline, AdditionalWalk):
            request = SaveAdditionalWalkRequest(baseline, self._request_id)
            operation = self.history_service.save_additional_walk
        elif expected_record is None:
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
        self.show_status("Saving Range-Walk evidence and preserving its source CSV")

    def request_history(self) -> None:
        if self.is_busy():
            return
        self._request_id += 1
        request = RangeWalkHistoryRequest(self._request_id)
        self._task = "history"
        self.start_worker(self.analysis_name, request, self.history_service.history)
        self._require_widget().show_history_busy()
        self.show_status("Loading saved Range-Walk baselines")

    def request_comparison(self) -> None:
        if self.is_busy():
            return
        baseline_id, walk_id = self._require_widget().selected_history_ids()
        if baseline_id is None or walk_id is None:
            return
        self._request_id += 1
        request = RangeWalkComparisonRequest(
            baseline_id, walk_id, self._request_id
        )
        self._task = "compare"
        self.start_worker(
            self.analysis_name, request, self.history_service.compare
        )
        self._require_widget().show_comparison_busy()
        self.show_status("Building saved Range-Walk RF comparison")

    def handle_success(self, result: object) -> bool:
        if isinstance(result, RangeWalkComparisonResult):
            return self._handle_comparison(result)
        if isinstance(result, SavedAdditionalWalkResult):
            return self._handle_saved_additional_walk(result)
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
            message = f"Unable to save Range-Walk evidence: {exc}"
            self._require_widget().show_persistence_error(message)
        elif operation == "history":
            message = f"Unable to load Range-Walk history: {exc}"
            self._require_widget().show_history_error(message)
        elif operation == "compare":
            message = f"Unable to compare saved Range-Walk evidence: {exc}"
            self._require_widget().show_comparison_error(message)
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
        self._require_widget().show_history(
            result.text, result.records, result.walks
        )
        self.show_status(
            f"Loaded {len(result.records)} baseline(s) and "
            f"{len(result.walks)} additional walk(s)"
        )
        return True

    def _handle_comparison(self, result: RangeWalkComparisonResult) -> bool:
        widget = self._require_widget()
        if (
            result.request_id != self._request_id
            or widget.selected_history_ids()
            != (result.baseline.baseline_id, result.walk.walk_id)
        ):
            self.show_status("Stale Range-Walk comparison was withheld")
            return True
        widget.show_comparison(result)
        self.show_status(
            f"Range-Walk comparison ready — {result.baseline.label} / "
            f"{result.walk.label}"
        )
        return True

    def _handle_saved_additional_walk(
        self, result: SavedAdditionalWalkResult
    ) -> bool:
        widget = self._require_widget()
        if (
            result.request_id != self._request_id
            or result.walk.source_path != widget.source_path
        ):
            self.show_status(
                "Additional walk was persisted, but its stale GUI result was withheld"
            )
            return True
        parent = widget.history_record(result.walk.parent_baseline_id)
        if parent is None:
            self.show_status(
                "Additional walk was persisted, but its parent is no longer selected"
            )
            return True
        if self._pending_save_revision != widget.draft_revision:
            widget.retain_persisted_walk_for_newer_draft(result.record)
            self.show_status(
                "Additional walk was persisted; newer visible metadata remains unsaved"
            )
            return True
        widget.show_persisted_additional_walk(result.walk, parent, result.record)
        self.show_status(f"Additional walk saved — {result.record.walk_id}")
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
