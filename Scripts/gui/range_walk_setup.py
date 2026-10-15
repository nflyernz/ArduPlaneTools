"""Page 2 state helpers for baseline and additional Range-Walk entry."""


def configure_walk_type(widget) -> None:
    """Switch Page 2 between Walk 1 and additional-walk entry."""
    additional = widget.walk_type_combo.currentData() == "additional"
    if additional and widget._current_walk_type == "baseline":
        widget._baseline_form_state = (
            widget.walk1_label_edit.text(),
            widget.antenna_edit.text(),
            tuple(field.text() for field in widget.landmark_name_edits),
            tuple(combo.currentData() for combo in widget.candidate_combos),
            tuple(
                field.text()
                for field in (
                    widget.tx_power_edit,
                    widget.packet_rate_edit,
                    widget.rf_mode_edit,
                    widget.dynamic_power_edit,
                )
            ),
        )
    widget._current_walk_type = "additional" if additional else "baseline"
    for control in (
        widget.parent_baseline_label,
        widget.parent_baseline_combo,
        widget.parent_reference_label,
        widget.parent_reference,
    ):
        control.setVisible(additional)
    widget.baseline_heading.setText(
        "<h2>Additional Walk &amp; Landmark Evidence</h2>"
        if additional
        else "<h2>Walk 1 — Baseline &amp; Landmarks</h2>"
    )
    widget.antenna_label.setText(
        "Test radio configuration:*"
        if additional
        else "Baseline radio configuration:*"
    )
    widget.walk_label.setText(
        "Walk label (optional):" if additional else "Walk 1 label (optional):"
    )
    widget.antenna_edit.setPlaceholderText(
        "Receiver, antennas, placement and orientation used for this walk"
        if additional
        else "Receiver, antennas, placement and orientation"
    )
    if additional:
        _show_additional_walk_form(widget)
    else:
        _show_walk1_form(widget)
    widget.baseline_summary.clear()
    widget._draft_changed()
    widget._update_controls()


def _show_additional_walk_form(widget) -> None:
    widget.baseline_explanation.setText(
        "Associate this recording with a saved Walk 1 baseline. The route, "
        "landmark order and RF settings are fixed references; physical route "
        "consistency is required by the procedure but is not independently "
        "verified by the software."
    )
    widget.walk1_label_edit.clear()
    widget.antenna_edit.clear()
    for combo in widget.candidate_combos:
        combo.setCurrentIndex(0)
        if combo.count():
            combo.setItemText(0, "Missing / unconfirmed")
    apply_parent_baseline(widget)
    widget._request_history()


def _show_walk1_form(widget) -> None:
    widget.baseline_explanation.setText(
        "Walk 1 records the baseline radio configuration and establishes "
        "the five physical landmarks. Landmark 5 is the safe turnaround."
    )
    if widget._baseline_form_state is not None:
        label, antenna, names, numbers, settings = widget._baseline_form_state
        widget.walk1_label_edit.setText(label)
        widget.antenna_edit.setText(antenna)
        for field, name in zip(widget.landmark_name_edits, names):
            field.setText(name)
        for combo, number in zip(widget.candidate_combos, numbers):
            combo.setCurrentIndex(max(0, combo.findData(number)))
        for field, value in zip(
            (
                widget.tx_power_edit,
                widget.packet_rate_edit,
                widget.rf_mode_edit,
                widget.dynamic_power_edit,
            ),
            settings,
        ):
            field.setText(value)
    for field in widget.landmark_name_edits:
        field.setReadOnly(False)
    for field in (
        widget.tx_power_edit,
        widget.packet_rate_edit,
        widget.rf_mode_edit,
        widget.dynamic_power_edit,
    ):
        field.setReadOnly(False)
    for position, title in enumerate(widget.landmark_title_labels, start=1):
        suffix = " (turnaround)" if position == 5 else ""
        title.setText(f"Landmark {position}{suffix}:")
    for combo in widget.candidate_combos:
        if combo.count():
            combo.setItemText(0, "Select candidate…")


def apply_parent_baseline(widget) -> None:
    """Show one selected baseline as immutable later-walk reference data."""
    if widget.walk_type_combo.currentData() != "additional":
        return
    parent = widget._history_records.get(widget.parent_baseline_combo.currentData())
    if parent is None:
        widget.parent_reference.setPlainText(
            "Select a validated saved Walk 1 baseline."
        )
        for field in widget.landmark_name_edits:
            field.clear()
            field.setReadOnly(True)
        widget._draft_changed()
        return
    widget.parent_reference.setPlainText(_baseline_reference_text(parent))
    for position, (title, field, name) in enumerate(
        zip(
            widget.landmark_title_labels,
            widget.landmark_name_edits,
            parent.landmark_names,
        ),
        start=1,
    ):
        suffix = " (turnaround)" if position == 5 else ""
        title.setText(f"Landmark {position}{suffix}:")
        field.setText(name)
        field.setReadOnly(True)
    for field, value in zip(
        (
            widget.tx_power_edit,
            widget.packet_rate_edit,
            widget.rf_mode_edit,
            widget.dynamic_power_edit,
        ),
        (
            parent.settings.tx_power,
            parent.settings.packet_rate,
            parent.settings.rf_mode,
            parent.settings.dynamic_power,
        ),
    ):
        field.setText(value)
        field.setReadOnly(True)
    widget._draft_changed()


def _baseline_reference_text(parent) -> str:
    landmarks = ", ".join(
        f"{position}. {name}"
        for position, name in enumerate(parent.landmark_names, start=1)
    )
    return (
        f"{parent.label}\nBaseline ID: {parent.baseline_id}\n"
        f"Baseline radio configuration: {parent.antenna}\n"
        f"Landmarks: {landmarks}\nTurnaround: {parent.turnaround}\n"
        "Configured RF settings: "
        f"{parent.settings.tx_power or 'Unknown'}; "
        f"{parent.settings.packet_rate or 'Unknown'}; "
        f"{parent.settings.rf_mode or 'Unknown'}; "
        f"dynamic power {parent.settings.dynamic_power or 'Unknown'}"
    )
