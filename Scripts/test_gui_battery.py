"""Focused tests for read-only threaded GUI Battery Analysis integration."""

import os
import threading
import time

import pandas as pd
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import analyses.battery as battery_analysis_module
from core.flight_window import FlightWindow
from core.log_reader import UnsupportedFirmwareError
from gui import MainWindow
import gui.battery_adapter as adapter_module


@pytest.fixture
def make_window(qt_app):
    windows = []

    def create(battery_adapter, **other_adapters):
        window = MainWindow(battery_adapter=battery_adapter, **other_adapters)
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window

    yield create

    for window in windows:
        if window._analysis_thread is not None:
            pytest.fail("test left an analysis worker active")
        window.close()
    qt_app.processEvents()


def _wait_until(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.005)
    qt_app.processEvents()
    assert predicate()


def _select_existing_bin(window, tmp_path, name="flight.bin"):
    selected = tmp_path / name
    selected.touch()
    window.set_selected_log(selected)
    return selected.resolve()


def test_adapter_reads_once_and_processes_each_flight_and_instance(
    monkeypatch, tmp_path
):
    selected = tmp_path / "pipeline.BIN"
    config = object()
    flights = (
        FlightWindow(1_000_000, 2_000_000),
        FlightWindow(3_000_000, 4_000_000),
    )

    class _FlightLog:
        def __init__(self):
            self.flights = flights
            self.battery = pd.DataFrame(
                (
                    {"TimeUS": 1_100_000, "Inst": 2},
                    {"TimeUS": 1_200_000, "Inst": 0},
                    {"TimeUS": 3_100_000, "Inst": 1},
                )
            )

        def get(self, name):
            assert name == "BAT"
            return self.battery

    flight_log = _FlightLog()
    analyses = {}
    calls = []

    def config_factory(path):
        calls.append(("config", path))
        return config

    class _Reader:
        def __init__(self, path, config=None):
            calls.append(("reader", path, config))

        def read(self):
            calls.append(("read",))
            return flight_log

    class _Processor:
        def __init__(self, supplied_log, window, instance, config=None):
            self.window = window
            self.instance = instance
            calls.append(("processor", supplied_log, window, instance, config))

        def analyse(self):
            result = object()
            analyses[(id(self.window), self.instance)] = result
            calls.append(("analyse", self.window, self.instance))
            return result

    def formatter(path, window, analysis):
        calls.append(("format", path, window, analysis))
        return f"report-{window.start_us}-{id(analysis)}"

    monkeypatch.setattr(adapter_module, "Config", config_factory)
    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "BatteryProcessor", _Processor)
    monkeypatch.setattr(adapter_module, "format_battery_report", formatter)

    report = adapter_module.analyse_battery_log(selected)

    assert report.index("FLIGHT 1 — BATTERY INSTANCE 0") < report.index(
        "FLIGHT 1 — BATTERY INSTANCE 2"
    ) < report.index("FLIGHT 2 — BATTERY INSTANCE 1")
    assert report.count("BATTERY INSTANCE 2") == 1
    assert "FLIGHT 2 — BATTERY INSTANCE 2" not in report
    assert calls.count(("read",)) == 1
    assert [call for call in calls if call[0] == "analyse"] == [
        ("analyse", flights[0], 0),
        ("analyse", flights[0], 2),
        ("analyse", flights[1], 1),
    ]
    assert [call for call in calls if call[0] == "format"] == [
        ("format", selected, flights[0], analyses[(id(flights[0]), 0)]),
        ("format", selected, flights[0], analyses[(id(flights[0]), 2)]),
        ("format", selected, flights[1], analyses[(id(flights[1]), 1)]),
    ]


def test_adapter_distinguishes_no_flights_no_telemetry_and_invalid_analysis(
    monkeypatch, tmp_path
):
    selected = tmp_path / "states.bin"

    class _Reader:
        flights = ()
        battery = pd.DataFrame()

        def __init__(self, _path, config=None):
            assert config is not None

        def read(self):
            return self

        def get(self, name):
            assert name == "BAT"
            return self.battery

    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    no_flights = adapter_module.analyse_battery_log(selected)
    assert "Flights : 0\n\nNo flights found." in no_flights

    flight = FlightWindow(1_000_000, 2_000_000)
    _Reader.flights = (flight,)
    _Reader.battery = pd.DataFrame(({"TimeUS": 5_000_000, "Inst": 7},))

    class _NoTelemetryProcessor:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("flight without BAT telemetry created a processor")

    monkeypatch.setattr(adapter_module, "BatteryProcessor", _NoTelemetryProcessor)
    no_telemetry = adapter_module.analyse_battery_log(selected)
    assert "No battery telemetry is available for this flight." in no_telemetry
    assert "BATTERY INSTANCE 7" not in no_telemetry

    _Reader.battery = pd.DataFrame(({"TimeUS": 1_500_000, "Inst": 4},))

    class _InvalidProcessor:
        def __init__(self, _flight_log, window, instance, config=None):
            assert window is flight
            assert instance == 4
            assert config is not None

        @staticmethod
        def analyse():
            return None

    monkeypatch.setattr(adapter_module, "BatteryProcessor", _InvalidProcessor)
    unavailable = adapter_module.analyse_battery_log(selected)
    assert "FLIGHT 1 — BATTERY INSTANCE 4" in unavailable
    assert "No valid battery analysis is available." in unavailable
    assert "No battery telemetry is available" not in unavailable


def test_adapter_never_uses_pack_persistence_and_leaves_data_unchanged(
    monkeypatch, tmp_path
):
    selected = tmp_path / "read-only.bin"
    persistent_data = tmp_path / "battery_packs.json"
    original = b'{"packs":["Pack 1"],"associations":{}}\n'
    persistent_data.write_bytes(original)
    flight = FlightWindow(1_000_000, 2_000_000)

    class _Reader:
        def __init__(self, _path, config=None):
            assert config is not None

        @staticmethod
        def read():
            class _FlightLog:
                flights = (flight,)

                @staticmethod
                def get(name):
                    assert name == "BAT"
                    return pd.DataFrame(({"TimeUS": 1_500_000, "Inst": 0},))

            return _FlightLog()

    class _Processor:
        def __init__(self, *_args, **_kwargs):
            pass

        @staticmethod
        def analyse():
            return None

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only GUI analysis accessed battery persistence")

    monkeypatch.setattr(adapter_module, "FlightReader", _Reader)
    monkeypatch.setattr(adapter_module, "BatteryProcessor", _Processor)
    monkeypatch.setattr(battery_analysis_module, "BatteryPackStore", forbidden)
    monkeypatch.setattr(battery_analysis_module, "fingerprint_log", forbidden)
    monkeypatch.setattr(
        battery_analysis_module,
        "BatteryPackHistoryRecorder",
        forbidden,
    )

    report = adapter_module.analyse_battery_log(selected)

    assert "No valid battery analysis is available." in report
    assert persistent_data.read_bytes() == original
    assert "BatteryPackStore" not in adapter_module.__dict__
    assert "BatteryPackHistoryRecorder" not in adapter_module.__dict__
    assert "fingerprint_log" not in adapter_module.__dict__


def test_battery_button_and_initial_read_only_report(make_window, qt_app, tmp_path):
    window = make_window(lambda _path: "Battery report")
    window.show_analysis_tab("Battery")
    qt_app.processEvents()

    assert not window.battery_analyse_button.isEnabled()
    report = window.report_for("Battery").toPlainText()
    assert report.startswith("Battery Analysis\n\nExamine battery consumption")
    assert "This analysis is read-only." in report
    assert "Battery Pack Management" in report

    _select_existing_bin(window, tmp_path, "valid.BIN")
    assert window.battery_analyse_button.isEnabled()


def test_battery_runs_off_thread_and_blocks_other_analyses(
    qt_app, make_window, tmp_path
):
    started = threading.Event()
    release = threading.Event()
    battery_calls = []
    other_calls = []
    worker_threads = []
    main_thread = threading.get_ident()

    def battery_adapter(path):
        battery_calls.append(path)
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return "BATTERY ANALYSIS\nNo valid battery analysis is available."

    def other_adapter(path):
        other_calls.append(path)
        return "unexpected"

    window = make_window(
        battery_adapter,
        landing_adapter=other_adapter,
        events_adapter=other_adapter,
        autotune_adapter=other_adapter,
        takeoff_adapter=other_adapter,
        stall_adapter=other_adapter,
    )
    window.show_analysis_tab("Battery")
    selected = _select_existing_bin(window, tmp_path)
    window.battery_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window._active_analysis == "Battery"
    for button in (
        window.battery_analyse_button,
        window.events_analyse_button,
        window.landing_analyse_button,
        window.autotune_analyse_button,
        window.takeoff_analyse_button,
        window.stall_analyse_button,
    ):
        assert not button.isEnabled()
    assert window.battery_analyse_button.text() == "Analysing…"
    window.start_battery_analysis()
    window.start_events_analysis()
    window.start_landing_analysis()
    window.start_autotune_analysis()
    window.start_takeoff_analysis()
    window.start_stall_analysis()
    assert battery_calls == [selected]
    assert other_calls == []

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)

    assert worker_threads[0] != main_thread
    assert "No valid battery analysis" in window.report_for("Battery").toPlainText()
    assert window.battery_analyse_button.isEnabled()


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (
            UnsupportedFirmwareError("ArduCopter is unsupported"),
            "Unsupported firmware.\nArduCopter is unsupported",
        ),
        (OSError("cannot read BIN"), "Unable to read log: cannot read BIN"),
        (
            RuntimeError("synthetic failure"),
            "Battery analysis failed unexpectedly: synthetic failure",
        ),
    ),
)
def test_battery_failures_recover_and_successful_retry_replaces_error(
    qt_app, make_window, tmp_path, failure, expected
):
    attempts = []

    def adapter(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise failure
        return "BATTERY ANALYSIS\nNo valid battery analysis is available."

    window = make_window(adapter)
    selected = _select_existing_bin(window, tmp_path)

    window.battery_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert expected in window.report_for("Battery").toPlainText()
    assert window.battery_analyse_button.isEnabled()

    window.battery_analyse_button.click()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    assert "No valid battery analysis" in window.report_for("Battery").toPlainText()
    assert "Error" not in window.report_for("Battery").toPlainText()
    assert attempts == [selected, selected]


def test_close_waits_for_active_battery_worker(qt_app, make_window, tmp_path):
    started = threading.Event()
    release = threading.Event()

    def adapter(_path):
        started.set()
        assert release.wait(2)
        return "BATTERY ANALYSIS"

    window = make_window(adapter)
    _select_existing_bin(window, tmp_path)
    window.battery_analyse_button.click()
    assert started.wait(1)
    qt_app.processEvents()

    assert window.close() is False
    assert window._close_after_worker
    assert window.isVisible()
    assert "Waiting for Battery analysis" in window.statusBar().currentMessage()

    release.set()
    _wait_until(qt_app, lambda: window._analysis_thread is None)
    _wait_until(qt_app, lambda: not window.isVisible())


def test_overview_labels_battery_analysis_and_navigates_by_internal_key(
    qt_app,
    make_window,
):
    window = make_window(lambda _path: "unused")

    assert window.overview_buttons["Battery"].text() == "Battery Analysis"
    assert "Connected to the GUI" not in window.overview_buttons[
        "Battery"
    ].description()
    window.overview_buttons["Battery"].click()
    qt_app.processEvents()

    assert window.current_analysis == "Battery"
    report = window.report_for("Battery").toPlainText()
    assert "This analysis is read-only." in report
    assert "Battery Pack Management" in report
    assert "ready" in window.statusBar().currentMessage()
