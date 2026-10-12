"""Focused tests for shared Analyse-menu log selection."""

from pathlib import Path

import analyse
import analyses.battery as battery_module
import analyses.event_timeline as event_timeline_module
import analyses.landing as landing_module
import pytest
from analyses import log_selector
from core.flight_data import FlightLog


@pytest.fixture(autouse=True)
def _reset_current_directory(monkeypatch):
    """Keep selector session state isolated between tests."""
    monkeypatch.setattr(log_selector, "_current_directory", Path("Logs"))


def _inputs(monkeypatch, *responses):
    """Provide deterministic responses to selector prompts."""
    values = iter(responses)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(values))


def test_default_logs_listing_and_numbered_selection(monkeypatch, tmp_path, capsys):
    """The default Logs directory lists and returns one numbered BIN path."""
    logs = tmp_path / "Logs"
    logs.mkdir()
    selected = logs / "log_0.bin"
    selected.touch()
    monkeypatch.chdir(tmp_path)
    _inputs(monkeypatch, "1")

    result = log_selector.select_log_input()

    assert result == [Path("Logs/log_0.bin")]
    output = capsys.readouterr().out
    assert "Directory: Logs" in output
    assert "1. log_0.bin" in output
    assert "A. Analyse all" not in output


def test_selector_prompt_explains_number_and_available_commands(monkeypatch, tmp_path):
    """Shared single-log and directory-capable callers see the right actions."""
    selected = tmp_path / "flight.bin"
    selected.touch()
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    prompts = []

    def choose(prompt):
        prompts.append(prompt)
        return "1"

    monkeypatch.setattr("builtins.input", choose)
    assert log_selector.select_log_input() == [selected]
    assert "Enter log number, D=directory, P=path, Q=back:" in prompts[-1]
    assert log_selector.select_log_input(allow_directory=True) == [selected]
    assert "Enter log number, A=all, D=directory, P=path, Q=back:" in prompts[-1]


def test_discovery_is_nonrecursive_case_insensitive_sorted_and_unique(tmp_path):
    """One discovery path handles mixed extension case deterministically."""
    (tmp_path / "zulu.BIN").touch()
    (tmp_path / "Alpha.bin").touch()
    (tmp_path / "ignore.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "nested.bin").touch()

    result = log_selector.discover_logs(tmp_path)

    assert [path.name for path in result] == ["Alpha.bin", "zulu.BIN"]
    assert len(result) == len(set(result))


def test_back_cancels_selection(monkeypatch, tmp_path):
    """Q returns cleanly without choosing input."""
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "q")

    assert log_selector.select_log_input() is None


def test_invalid_selection_retries(monkeypatch, tmp_path, capsys):
    """Invalid input leaves the selector active for a later valid choice."""
    selected = tmp_path / "selected.bin"
    selected.touch()
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "invalid", "1")

    assert log_selector.select_log_input() == [selected]
    assert "Invalid selection." in capsys.readouterr().out


def test_change_directory_rejects_invalid_then_lists_valid(
    monkeypatch,
    tmp_path,
    capsys,
):
    """D reports an invalid directory and retains the selector workflow."""
    initial = tmp_path / "initial"
    initial.mkdir()
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    selected = chosen / "flight.BIN"
    selected.touch()
    monkeypatch.setattr(log_selector, "_current_directory", initial)
    _inputs(monkeypatch, "d", str(tmp_path / "missing"), "d", str(chosen), "1")

    assert log_selector.select_log_input() == [selected]
    output = capsys.readouterr().out
    assert "Invalid directory." in output
    assert f"Directory: {chosen}" in output


def test_manual_file_path_accepts_bin_case_insensitively(monkeypatch, tmp_path):
    """P accepts one existing BIN file and preserves the entered Path."""
    selected = tmp_path / "manual.BIN"
    selected.touch()
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "p", str(selected))

    assert log_selector.select_log_input() == [selected]


def test_directory_choice_expands_user_home(monkeypatch, tmp_path):
    """D expands a leading tilde before validating and remembering a directory."""
    home = tmp_path / "home"
    selected_directory = home / "flight-logs"
    selected_directory.mkdir(parents=True)
    selected = selected_directory / "flight.bin"
    selected.touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "d", "~/flight-logs", "1")

    assert log_selector.select_log_input() == [selected]
    assert log_selector._current_directory == selected_directory


def test_manual_file_path_expands_user_home(monkeypatch, tmp_path):
    """P expands a leading tilde for a manually entered BIN file."""
    home = tmp_path / "home"
    home.mkdir()
    selected = home / "manual.BIN"
    selected.touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "p", "~/manual.BIN")

    assert log_selector.select_log_input() == [selected]


def test_single_log_mode_rejects_manual_directory_and_all_option(
    monkeypatch,
    tmp_path,
    capsys,
):
    """Single-log callers cannot select or manually submit a directory."""
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "a", "p", str(tmp_path), "q")

    assert log_selector.select_log_input() is None
    output = capsys.readouterr().out
    assert "A. Analyse all" not in output
    assert "Invalid selection." in output
    assert "A directory is not valid for this analysis." in output


def test_landing_mode_analyzes_all_current_directory_logs(
    monkeypatch,
    tmp_path,
    capsys,
):
    """A is displayed and returns every immediate BIN path for Landing."""
    first = tmp_path / "a.bin"
    second = tmp_path / "B.BIN"
    first.touch()
    second.touch()
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "a")

    assert log_selector.select_log_input(allow_directory=True) == [first, second]
    assert "A. Analyse all logs in this directory" in capsys.readouterr().out


def test_landing_manual_directory_uses_same_discovery(monkeypatch, tmp_path):
    """Landing's manual directory path expands through shared discovery."""
    directory = tmp_path / "manual"
    directory.mkdir()
    selected = directory / "flight.bin"
    selected.touch()
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "p", str(directory))

    assert log_selector.select_log_input(allow_directory=True) == [selected]
    assert log_selector._current_directory == directory


def test_empty_directory_remains_navigable(monkeypatch, tmp_path, capsys):
    """An empty directory reports no logs and still permits Back."""
    monkeypatch.setattr(log_selector, "_current_directory", tmp_path)
    _inputs(monkeypatch, "a", "q")

    assert log_selector.select_log_input(allow_directory=True) is None
    assert capsys.readouterr().out.count("No BIN logs found in this directory.") >= 2


def test_current_directory_is_retained_for_later_selector_calls(
    monkeypatch,
    tmp_path,
):
    """A directory chosen in one workflow remains current for this process."""
    initial = tmp_path / "initial"
    initial.mkdir()
    remembered = tmp_path / "remembered"
    remembered.mkdir()
    selected = remembered / "flight.bin"
    selected.touch()
    monkeypatch.setattr(log_selector, "_current_directory", initial)
    _inputs(monkeypatch, "d", str(remembered), "q", "1")

    assert log_selector.select_log_input() is None
    assert log_selector.select_log_input() == [selected]


def test_implemented_presentations_receive_shared_selector_paths(monkeypatch):
    """Single-log workflows receive one Path and Landing receives the full list."""
    single = Path("chosen/flight.bin")
    multiple = [Path("chosen/a.bin"), Path("chosen/b.BIN")]
    received = {}

    class _Reader:
        def __init__(self, path, config=None):
            received.setdefault("readers", []).append((path, config))

        def read(self):
            return FlightLog()

    monkeypatch.setattr(event_timeline_module, "select_log_input", lambda: [single])
    monkeypatch.setattr(event_timeline_module, "FlightReader", _Reader)
    event_timeline_module.EventTimelineAnalysis().run()

    monkeypatch.setattr(battery_module, "select_log_input", lambda: [single])
    monkeypatch.setattr(battery_module, "FlightReader", _Reader)
    battery_module.BatteryAnalysisPresentation(config=object()).run()

    loaded = []
    landing = landing_module.LandingAnalysis(config=object())
    monkeypatch.setattr(
        landing_module,
        "select_log_input",
        lambda *, allow_directory: multiple if allow_directory else None,
    )
    monkeypatch.setattr(
        landing,
        "load_telemetry",
        lambda path: loaded.append(path) or FlightLog(),
    )
    landing.run()

    assert [path for path, _config in received["readers"]] == [
        str(single),
        str(single),
    ]
    assert loaded == multiple


def test_event_timeline_reports_log_read_failure(monkeypatch, capsys):
    """An ordinary read failure returns a concise Event Timeline message."""
    selected = Path("chosen/unreadable.bin")

    class _Reader:
        def __init__(self, path):
            assert path == str(selected)

        def read(self):
            raise OSError("permission denied")

    monkeypatch.setattr(event_timeline_module, "select_log_input", lambda: [selected])
    monkeypatch.setattr(event_timeline_module, "FlightReader", _Reader)

    event_timeline_module.EventTimelineAnalysis().run()

    assert "Unable to read log: permission denied" in capsys.readouterr().out


def test_battery_analysis_reports_log_read_failure(monkeypatch, capsys):
    """An ordinary read failure returns a concise Battery Analysis message."""
    selected = Path("chosen/unreadable.bin")

    class _Reader:
        def __init__(self, path, config=None):
            assert path == str(selected)

        def read(self):
            raise OSError("permission denied")

    monkeypatch.setattr(battery_module, "select_log_input", lambda: [selected])
    monkeypatch.setattr(battery_module, "FlightReader", _Reader)

    battery_module.BatteryAnalysisPresentation(
        pack_id="Pack 1",
        config=object(),
    ).run()

    assert "Unable to read log: permission denied" in capsys.readouterr().out


def test_event_and_battery_return_directly_to_menu(monkeypatch):
    """Menu options 2 and 3 do not consume an extra return-pause response."""
    calls = []
    choices = iter(("2", "3", "0"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))
    monkeypatch.setattr(
        event_timeline_module.EventTimelineAnalysis,
        "run",
        lambda _self: calls.append("event"),
    )
    monkeypatch.setattr(
        battery_module.BatteryAnalysisPresentation,
        "run",
        lambda _self: calls.append("battery"),
    )

    analyse.menu()

    assert calls == ["event", "battery"]


def test_placeholder_functions_remain_unimplemented(capsys):
    """The existing placeholder entries retain their existing behavior."""
    analyse.cruise_analysis()
    analyse.sensor_diagnostics()
    analyse.log_summary()

    assert capsys.readouterr().out.count("Not implemented.") == 3


def test_menu_labels_and_dispatches_placeholder_entries(monkeypatch, capsys):
    """Placeholder status is visible without changing options 4, 6, or 7."""
    choices = iter(("4", "6", "7", "0"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(choices))

    analyse.menu()

    output = capsys.readouterr().out
    assert "4. Cruise Analysis (not implemented)" in output
    assert "6. Sensor Diagnostics (not implemented)" in output
    assert "7. Log Summary (not implemented)" in output
    assert output.count("Not implemented.") == 3
