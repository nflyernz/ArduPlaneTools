"""Portable tests for the session-only Range-Walk Walk 1 baseline."""

import os
from datetime import timedelta
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel, QLineEdit

from core.range_walk import LandmarkMarker, WalkSettings
from gui.range_walk_adapter import (
    RangeWalkPreviewResult,
    create_walk1_baseline,
    format_walk1_baseline_summary,
)
from gui.range_walk_widget import RangeWalkPreviewWidget
from test_range_walk import BASE


def _preview(count=5, source=Path("walk1.csv")):
    markers = tuple(
        LandmarkMarker(
            BASE + timedelta(seconds=2 + 6 * index),
            BASE + timedelta(seconds=4 + 6 * index),
            21,
        )
        for index in range(count)
    )
    return RangeWalkPreviewResult(
        source.resolve(),
        1,
        BASE,
        BASE + timedelta(seconds=32),
        330,
        markers,
        "higher",
        "higher",
        True,
        "Auto selected higher.",
        "preview result",
        "0" * 64,
    )


def _baseline(preview, numbers=(1, 2, 3, 4, 5), **overrides):
    values = {
        "landmark_names": ("Gate", "Tree", "Fence", "Shed", "Far field"),
        "antenna": "Original vertical antenna, receiver bay",
        "label": "",
        "settings": WalkSettings(),
    }
    values.update(overrides)
    return create_walk1_baseline(preview, numbers, **values)


def test_exactly_five_candidates_map_chronologically_without_redetection():
    preview = _preview()

    baseline = _baseline(preview)

    assert baseline.label == "Walk 1 — walk1"
    assert baseline.candidates is preview.markers
    assert baseline.candidate_numbers == (1, 2, 3, 4, 5)
    assert all(
        selected is detected
        for selected, detected in zip(baseline.landmarks, preview.markers)
    )
    assert baseline.settings == WalkSettings()
    summary = format_walk1_baseline_summary(baseline)
    assert "Walk 1 baseline" in summary
    assert "TX power: Unknown" in summary
    assert "prevent a later like-for-like comparison claim" in summary
    assert "exact confirmed marker evidence" in summary


def test_extra_candidates_can_be_excluded_without_reordering():
    preview = _preview(7)

    baseline = _baseline(preview, (1, 2, 4, 6, 7))

    assert baseline.candidate_numbers == (1, 2, 4, 6, 7)
    assert baseline.landmarks == tuple(
        preview.markers[index - 1] for index in (1, 2, 4, 6, 7)
    )


@pytest.mark.parametrize(
    ("count", "numbers", "message"),
    (
        (4, (1, 2, 3, 4, None), "five confirmed landmarks"),
        (6, (1, 2, 2, 4, 5), "distinct, increasing"),
        (6, (1, 3, 2, 4, 5), "distinct, increasing"),
        (6, (1, None, 3, 4, 5), "five confirmed landmarks"),
    ),
)
def test_missing_duplicate_and_out_of_order_mappings_are_rejected(
    count, numbers, message
):
    with pytest.raises(ValueError, match=message):
        _baseline(_preview(count), numbers)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"landmark_names": ("Gate", "", "Fence", "Shed", "Far")}, "physical name"),
        ({"landmark_names": ("Gate", "Tree", "Fence", "Shed", "")}, "physical name"),
        ({"antenna": "  "}, "baseline radio configuration"),
    ),
)
def test_required_walk1_metadata_is_validated(overrides, message):
    with pytest.raises(ValueError, match=message):
        _baseline(_preview(), **overrides)


def _complete_widget_draft(widget):
    widget.antenna_edit.setText("Original antenna under right wing")
    for number, field in enumerate(widget.landmark_name_edits, start=1):
        field.setText(f"Physical point {number}")


def test_page_navigation_preserves_mapping_and_metadata(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    preview = _preview()
    widget.show_result(preview)

    assert widget.pages.currentIndex() == 0
    assert widget.next_button.isEnabled()
    widget.next_button.click()
    _complete_widget_draft(widget)
    widget.candidate_combos[2].setCurrentIndex(3)
    widget.back_button.click()
    widget.next_button.click()

    assert widget.pages.currentIndex() == 1
    assert widget.antenna_edit.text() == "Original antenna under right wing"
    assert widget.candidate_combos[2].currentData() == 3
    assert widget.candidate_evidence_labels[2].text() == (
        "15:00:14 → 15:00:16 (2.0 s)"
    )
    widget.close()


def test_new_csv_updates_default_label_but_preserves_a_custom_label(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    widget.show_result(_preview(source=Path("first.csv")))
    assert widget.walk1_label_edit.text() == "Walk 1 — first"

    widget.show_result(_preview(source=Path("second.csv")))
    assert widget.walk1_label_edit.text() == "Walk 1 — second"

    widget.walk1_label_edit.setText("Original antenna field run")
    widget.show_result(_preview(source=Path("third.csv")))
    assert widget.walk1_label_edit.text() == "Original antenna field run"
    widget.close()


def test_widget_saves_in_memory_baseline_with_exact_preview_markers(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    preview = _preview()
    widget.show_result(preview)
    widget.next_button.click()
    _complete_widget_draft(widget)

    widget.save_baseline_button.click()

    saved = widget.saved_baseline
    assert saved is not None
    assert saved.source_path == preview.source_path
    assert saved.turnaround == "Physical point 5"
    assert saved.candidates is preview.markers
    assert all(left is right for left, right in zip(saved.landmarks, preview.markers))
    assert "memory only" in widget.baseline_state_label.text()
    assert "Unknown" in widget.baseline_summary.toPlainText()
    widget.close()


def test_page_has_no_duplicate_turnaround_input_and_requires_landmark5(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    widget.show_result(_preview())
    widget.next_button.click()

    assert widget.findChild(QLineEdit, "rangeWalkBaselineTurnaround") is None
    assert "Baseline radio configuration:*" in {
        label.text() for label in widget.findChildren(QLabel)
    }
    assert widget.antenna_edit.placeholderText() == (
        "Receiver, antennas, placement and orientation"
    )
    assert "Incomplete draft" in widget.baseline_state_label.text()
    widget.antenna_edit.setText("Original antenna under right wing")
    for field in widget.landmark_name_edits[:4]:
        field.setText("Named point")
    widget.save_baseline_button.click()

    assert widget.saved_baseline is None
    assert widget.baseline_state_label.text().startswith("Incomplete draft")
    assert "physical name for all five landmarks" in widget.baseline_state_label.text()
    widget.close()


def test_rf_settings_title_font_is_larger_without_changing_field_font(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)

    assert widget.rf_settings_group.font().pointSizeF() > widget.font().pointSizeF()
    assert widget.rf_settings_content.font().pointSizeF() == widget.font().pointSizeF()
    assert widget.tx_power_edit.font().pointSizeF() == widget.font().pointSizeF()
    widget.close()


def test_fewer_than_five_candidates_prevent_widget_acceptance(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    widget.show_result(_preview(4))
    widget.next_button.click()
    _complete_widget_draft(widget)

    widget.save_baseline_button.click()

    assert widget.saved_baseline is None
    assert "five confirmed landmarks" in widget.baseline_state_label.text()
    widget.close()


def test_extra_candidate_mapping_and_unknown_settings_are_retained(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    widget.show_result(_preview(7))
    widget.next_button.click()
    _complete_widget_draft(widget)
    for combo, number in zip(widget.candidate_combos, (1, 2, 4, 6, 7)):
        combo.setCurrentIndex(number)
    widget.tx_power_edit.setText("100 mW")

    widget.save_baseline_button.click()

    saved = widget.saved_baseline
    assert saved is not None
    assert saved.candidate_numbers == (1, 2, 4, 6, 7)
    assert saved.settings == WalkSettings(tx_power="100 mW")
    assert "Packet rate: Unknown" in widget.baseline_summary.toPlainText()
    widget.close()


def test_evidence_changes_invalidate_saved_baseline_but_navigation_does_not(qt_app):
    widget = RangeWalkPreviewWidget(lambda: None, lambda: None)
    widget.set_source(Path("walk1.csv"))
    widget.show_result(_preview())
    widget.next_button.click()
    _complete_widget_draft(widget)
    widget.save_baseline_button.click()
    saved = widget.saved_baseline

    widget.back_button.click()
    widget.next_button.click()
    assert widget.saved_baseline is saved

    widget.back_button.click()
    widget.inverse_button.click()
    assert widget.saved_baseline is None
    assert not widget.next_button.isEnabled()

    widget.show_result(_preview())
    widget.next_button.click()
    widget.save_baseline_button.click()
    assert widget.saved_baseline is not None
    widget.show_busy()
    assert widget.saved_baseline is None

    widget.show_result(_preview())
    widget.next_button.click()
    widget.save_baseline_button.click()
    assert widget.saved_baseline is not None
    widget.set_source(Path("replacement.csv"))
    assert widget.saved_baseline is None
    assert widget.pages.currentIndex() == 0
    widget.close()


def test_range_walk_help_describes_baseline_scope_and_invalidation():
    root = Path(__file__).parents[1]
    readme = (root / "Docs/gui_help/range_walk_comparison/README.md").read_text()
    glossary = (
        root / "Docs/gui_help/range_walk_comparison/glossary.md"
    ).read_text()
    procedure = (
        root / "Docs/gui_help/range_walk_comparison/procedure.md"
    ).read_text()

    assert "Walk 1 establishes the baseline" in readme
    assert "Walk 1 establishes the baseline for every subsequent comparison" in procedure
    assert "five physical landmarks" in readme
    assert "four sections" in readme
    assert "Later walks repeat the same route and landmarks" in readme
    assert "Exclude extra candidates" in procedure
    assert "rather than guessed or assigned automatically" in readme
    assert "Leave missing markers unassigned" in procedure
    assert "no separate description field" in glossary
    for text in (glossary, procedure):
        assert "landmark 5" in text.lower()
    assert "never moved out of recorded order" in glossary
    assert "Optional operator-entered" in glossary
    for required in (
        "Record exactly what changes between walks",
    ):
        assert required in readme
    for required in (
        "Repeat the same walking route, five landmarks, marker holds and turnaround",
        "Keep the transmitter RF settings unchanged",
        "Change only the radio configuration you intend to compare",
    ):
        assert required in procedure
    assert "checksum-named preserved copy" in glossary
    assert "not yet available in the GUI" in readme
    for text in (glossary, procedure):
        assert "Baseline radio configuration" in text
    assert "Update saved Walk 1" in glossary
    assert "Update saved Walk 1" in procedure
    assert "Test radio configuration" in glossary
    assert "four detected markers represent landmarks 1–4" in procedure
    assert "does not prove that the operator failed to visit that landmark" in glossary
