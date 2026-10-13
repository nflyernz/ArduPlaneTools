"""GUI contracts for optional EdgeTX evidence beside Radio Link BIN results."""

from datetime import datetime
import os
from pathlib import Path
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog

from analyses.radio_link import _candidate_preview
from core.edgetx import EdgeTxAlignment, EdgeTxOverlay, EdgeTxRow, EdgeTxSession
from gui import MainWindow
from gui.pack_management_adapter import BatteryPackManagementService
from gui.pack_performance_adapter import BatteryPackPerformanceService
import gui.radio_link_adapter as adapter_module
from gui.radio_link_adapter import (
    EdgeTxCandidatePreview,
    EdgeTxCandidateSet,
    EdgeTxGuiOverlay,
    RadioLinkCsvService,
    RadioLinkGuiResult,
    automatic_overlay_result,
)
from test_edgetx_radio_link import _flight, _gap, _pattern_rows, _result, _row, _write


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def _session(path: Path) -> EdgeTxSession:
    row = EdgeTxRow(
        datetime(2026, 10, 5, 12),
        {
            "RQly(%)": 80,
            "1RSS(dB)": -90,
            "2RSS(dB)": None,
            "RSNR(dB)": 2,
            "RFMD": 2,
            "TPWR(mW)": 50,
        },
        None,
        "",
        "active",
    )
    return EdgeTxSession(path, (), [row], [], 1)


def _overlay(path: Path, pairing="accepted automatic") -> EdgeTxOverlay:
    return EdgeTxOverlay(
        _session(path),
        pairing,
        EdgeTxAlignment("unavailable", reason="test evidence"),
        ["episode alignment unavailable: test evidence"],
    )


def _preview(path: Path, pairing="accepted automatic") -> EdgeTxCandidatePreview:
    overlay = _overlay(path, pairing)
    return EdgeTxCandidatePreview(path, "candidate diagnostic", overlay.session, overlay)


@pytest.fixture
def make_window(qt_app, tmp_path):
    windows = []

    def create(adapter, csv_service=None, **adapters):
        window = MainWindow(
            radio_link_adapter=adapter,
            radio_link_csv_service=csv_service,
            pack_management_service=BatteryPackManagementService(
                pack_store_path=tmp_path / "packs.json",
                history_store_path=tmp_path / "history.json",
            ),
            pack_performance_service=BatteryPackPerformanceService(
                pack_store_path=tmp_path / "packs.json",
                history_store_path=tmp_path / "history.json",
            ),
            **adapters,
        )
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left a Radio Link worker active")
        window.close()
    qt_app.processEvents()


def _select_and_analyse(qt_app, window, tmp_path, adapter_calls, name="radio.bin"):
    path = (tmp_path / name).resolve()
    path.touch()
    window.set_selected_log(path)
    window._radio_link.widget.analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert adapter_calls == [path]
    return path


def test_candidate_discovery_matches_cli_diagnostics_and_keeps_bad_files(tmp_path):
    bin_path = tmp_path / "aircraft.bin"
    good = _write(tmp_path, _pattern_rows(), name="good.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("Date,Time\n2026-10-05,00:00:00.000\n")
    context = RadioLinkGuiResult(
        bin_path,
        "summary",
        "detail",
        _flight(),
        _result((10.2, 10.8)),
    )

    discovered = RadioLinkCsvService.discover(context)
    by_name = {candidate.path.name: candidate for candidate in discovered.candidates}
    cli_session, cli_automatic, cli_hint = _candidate_preview(
        good, context.detection, context.flight_log
    )

    assert discovered.source_path == bin_path
    assert by_name["good.csv"].hint == cli_hint
    assert by_name["good.csv"].session == cli_session
    assert by_name["good.csv"].automatic_overlay == cli_automatic
    assert by_name["bad.csv"].session is None
    assert by_name["bad.csv"].hint.startswith("unusable CSV:")


def test_automatic_pairing_requires_exactly_one_eligible_candidate(tmp_path):
    source = tmp_path / "aircraft.bin"
    context = RadioLinkGuiResult(source, "summary", "detail", object(), object())
    one = EdgeTxCandidateSet(source, (_preview(tmp_path / "one.csv"),))

    selected = automatic_overlay_result(context, one, 7)
    assert isinstance(selected, EdgeTxGuiOverlay)
    assert selected.csv_path.name == "one.csv"
    assert "Pairing: Automatic" in selected.text

    ambiguous = EdgeTxCandidateSet(
        source,
        (_preview(tmp_path / "one.csv"), _preview(tmp_path / "two.csv")),
    )
    assert "ambiguous" in automatic_overlay_result(context, ambiguous, 8)

    unsuitable = EdgeTxCandidateSet(
        source,
        (_preview(tmp_path / "one.csv", "accepted explicit"),),
    )
    assert "no candidate" in automatic_overlay_result(context, unsuitable, 9)
    assert "no nearby" in automatic_overlay_result(
        context, EdgeTxCandidateSet(source, ()), 10
    )


def test_explicit_overlay_preserves_coarse_warnings_partial_coverage_and_zeros(
    tmp_path,
):
    rows = [
        _row(-500, offset=3600, quality=1, rssi=-120),
        *_pattern_rows(offset=3600, gps=True),
    ]
    path = _write(tmp_path, rows)
    context = RadioLinkGuiResult(
        tmp_path / "aircraft.bin",
        "summary",
        "detail",
        _flight(),
        _result((10, 14)),
    )
    request = adapter_module.EdgeTxOverlayRequest(context, path, 1)

    result = RadioLinkCsvService.explicit(request)

    assert result.overlay.pairing == "accepted explicit"
    assert result.overlay.alignment.status == "coarse"
    assert result.overlay.episode_rf == {}
    assert "Pairing: Explicit" in result.text
    assert "Alignment: Coarse" in result.text
    assert "local timezone" in result.text
    assert "partial file coverage" in result.text
    assert "No episode-specific RF minima established" in result.text
    assert "Lowest RQly: 20%" in result.text
    assert "Lowest RQly: 0%" not in result.text


def test_explicit_service_uses_existing_analysis_with_explicit_true(
    monkeypatch, tmp_path
):
    path = tmp_path / "chosen.csv"
    session = _session(path)
    overlay = _overlay(path, "accepted explicit")
    context = RadioLinkGuiResult(
        tmp_path / "aircraft.bin", "summary", "detail", object(), object()
    )
    calls = []

    monkeypatch.setattr(adapter_module, "read_edgetx_csv", lambda supplied: session)
    monkeypatch.setattr(
        adapter_module,
        "analyse_edgetx",
        lambda detection, flight, supplied, **kwargs: calls.append(
            (detection, flight, supplied, kwargs)
        )
        or overlay,
    )

    result = RadioLinkCsvService.explicit(
        adapter_module.EdgeTxOverlayRequest(context, path, 4)
    )

    assert calls == [(context.detection, context.flight_log, session, {"explicit": True})]
    assert result.request_id == 4
    assert "Pairing: Explicit" in result.text


def test_optional_workflow_keeps_bin_cache_and_removes_only_overlay(
    qt_app, tmp_path, make_window
):
    adapter_calls = []
    csv_path = tmp_path / "radio.csv"

    def adapter(path):
        adapter_calls.append(path)
        return RadioLinkGuiResult(path, "aircraft summary", "aircraft detail", object(), object())

    class Service:
        def discover(self, context):
            return EdgeTxCandidateSet(context.source_path, (_preview(csv_path),))

        def explicit(self, request):
            return EdgeTxGuiOverlay(
                request.context.source_path,
                request.csv_path,
                request.request_id,
                "EdgeTX explicit evidence",
                _overlay(request.csv_path, "accepted explicit"),
            )

    window = make_window(adapter, Service())
    widget = window._radio_link.widget
    _select_and_analyse(qt_app, window, tmp_path, adapter_calls)

    assert widget.report.toPlainText() == "aircraft summary"
    widget.discover_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "candidate diagnostic" in widget.candidate_hint.text()

    widget.automatic_button.click()
    assert "aircraft summary" in widget.report.toPlainText()
    assert "Pairing: Automatic" in widget.report.toPlainText()
    widget.detail_button.click()
    assert "aircraft detail" in widget.report.toPlainText()

    widget.remove_overlay_button.click()
    assert widget.report.toPlainText() == "aircraft detail"
    assert widget.result is not None

    widget.use_candidate_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "EdgeTX explicit evidence" in widget.report.toPlainText()
    assert adapter_calls == [widget.result.source_path]
    assert not (tmp_path / "packs.json").exists()
    assert not (tmp_path / "history.json").exists()


def test_malformed_candidate_failure_preserves_bin_and_allows_retry(
    qt_app, tmp_path, make_window
):
    adapter_calls = []
    bad = tmp_path / "bad.csv"
    good = tmp_path / "good.csv"

    def adapter(path):
        adapter_calls.append(path)
        return RadioLinkGuiResult(path, "aircraft summary", "detail", object(), object())

    class Service:
        def discover(self, context):
            return EdgeTxCandidateSet(
                context.source_path,
                (
                    EdgeTxCandidatePreview(bad, "unusable CSV: malformed", None, None),
                    _preview(good, "accepted explicit"),
                ),
            )

        def explicit(self, request):
            if request.csv_path == bad:
                raise ValueError("malformed CSV")
            return EdgeTxGuiOverlay(
                request.context.source_path,
                request.csv_path,
                request.request_id,
                "recovered transmitter evidence",
                _overlay(good, "accepted explicit"),
            )

    window = make_window(adapter, Service())
    widget = window._radio_link.widget
    _select_and_analyse(qt_app, window, tmp_path, adapter_calls)
    widget.discover_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    widget.use_candidate_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert widget.report.toPlainText() == "aircraft summary"
    assert "Unable to use EdgeTX CSV: malformed CSV" in widget.candidate_hint.text()

    widget.candidate_combo.setCurrentIndex(1)
    widget.use_candidate_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "recovered transmitter evidence" in widget.report.toPlainText()
    assert adapter_calls == [widget.result.source_path]


def test_browse_uses_csv_filter_and_cancel_preserves_overlay(
    qt_app, tmp_path, make_window, monkeypatch
):
    calls = []
    chosen = tmp_path / "elsewhere.CSV"

    def adapter(path):
        calls.append(path)
        return RadioLinkGuiResult(path, "summary", "detail", object(), object())

    class Service:
        def explicit(self, request):
            calls.append(request.csv_path)
            return EdgeTxGuiOverlay(
                request.context.source_path,
                request.csv_path,
                request.request_id,
                "chosen evidence",
                _overlay(request.csv_path, "accepted explicit"),
            )

    window = make_window(adapter, Service())
    widget = window._radio_link.widget
    _select_and_analyse(qt_app, window, tmp_path, calls)
    calls.clear()
    dialog_calls = []
    replies = iter([(str(chosen), ""), ("", "")])

    def dialog(*args):
        dialog_calls.append(args)
        return next(replies)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", dialog)
    widget.browse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    previous = widget.report.toPlainText()
    widget.browse_button.click()

    assert calls == [chosen.resolve()]
    assert widget.report.toPlainText() == previous
    assert "EdgeTX CSV files (*.csv *.CSV)" in dialog_calls[0][3]


def test_older_csv_request_cannot_replace_a_newer_overlay(
    qt_app, tmp_path, make_window
):
    adapter_calls = []

    def adapter(path):
        adapter_calls.append(path)
        return RadioLinkGuiResult(path, "summary", "detail", object(), object())

    window = make_window(adapter)
    widget = window._radio_link.widget
    source = _select_and_analyse(qt_app, window, tmp_path, adapter_calls)
    current = EdgeTxGuiOverlay(
        source,
        tmp_path / "new.csv",
        2,
        "new evidence",
        _overlay(tmp_path / "new.csv", "accepted explicit"),
    )
    window._radio_link._csv_request_id = 2
    assert window._radio_link.handle_success(current)

    stale = EdgeTxGuiOverlay(
        source,
        tmp_path / "old.csv",
        1,
        "old evidence",
        _overlay(tmp_path / "old.csv", "accepted explicit"),
    )
    assert window._radio_link.handle_success(stale)

    assert widget.overlay == current
    assert "new evidence" in widget.report.toPlainText()
    assert "old evidence" not in widget.report.toPlainText()
    assert "Stale EdgeTX overlay was withheld" in window.statusBar().currentMessage()


def test_bin_change_withholds_stale_csv_result_and_close_waits_for_worker(
    qt_app, tmp_path, make_window
):
    started = threading.Event()
    release = threading.Event()
    adapter_calls = []

    def adapter(path):
        adapter_calls.append(path)
        return RadioLinkGuiResult(path, "summary", "detail", object(), object())

    class Service:
        def discover(self, context):
            started.set()
            assert release.wait(2)
            return EdgeTxCandidateSet(
                context.source_path,
                (_preview(tmp_path / "candidate.csv"),),
            )

    window = make_window(adapter, Service())
    widget = window._radio_link.widget
    _select_and_analyse(qt_app, window, tmp_path, adapter_calls, "first.bin")
    widget.discover_button.click()
    assert started.wait(1)
    qt_app.processEvents()
    assert not window.autotune_analyse_button.isEnabled()
    assert not window.choose_log_button.isEnabled()

    second = (tmp_path / "second.bin").resolve()
    second.touch()
    window.set_selected_log(second)
    assert widget.result is None
    window.close()
    assert window.isVisible()

    release.set()
    _wait_until(
        qt_app,
        lambda: window._analysis_thread is None and not window.isVisible(),
    )
    assert widget.candidates is None
    assert adapter_calls == [(tmp_path / "first.bin").resolve()]
