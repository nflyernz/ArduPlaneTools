"""Focused tests for writable application-data paths."""

import pytest

from core.application_data import application_data_directory
from core.battery_pack_history import (
    DEFAULT_HISTORY_PATH as BATTERY_HISTORY_PATH,
    BatteryPackHistoryStore,
)
from core.battery_pack_store import DEFAULT_STORE_PATH, BatteryPackStore
from core.range_walk_history import (
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_HISTORY_PATH as RANGE_WALK_HISTORY_PATH,
    RangeWalkHistoryStore,
)


def test_macos_application_data_path_is_not_created(tmp_path):
    home = tmp_path / "user"

    path = application_data_directory(platform_name="darwin", home=home)

    assert path == home / "Library/Application Support/ArduPlaneTools"
    assert not home.exists()


def test_windows_application_data_path_uses_localappdata(tmp_path):
    local_app_data = tmp_path / "LocalAppData"

    path = application_data_directory(
        platform_name="win32",
        environ={"LOCALAPPDATA": str(local_app_data)},
        home=tmp_path / "unused-home",
    )

    assert path == local_app_data / "ArduPlaneTools"
    assert not local_app_data.exists()


def test_windows_without_localappdata_fails_explicitly(tmp_path):
    with pytest.raises(RuntimeError, match="LOCALAPPDATA is unavailable"):
        application_data_directory(
            platform_name="win32",
            environ={},
            home=tmp_path,
        )


def test_windows_rejects_cwd_relative_localappdata(tmp_path):
    with pytest.raises(
        RuntimeError,
        match="LOCALAPPDATA must be an absolute path",
    ):
        application_data_directory(
            platform_name="win32",
            environ={"LOCALAPPDATA": "relative/path"},
            home=tmp_path,
        )


def test_linux_application_data_path_uses_xdg_data_home(tmp_path):
    xdg_data_home = tmp_path / "xdg-data"

    path = application_data_directory(
        platform_name="linux",
        environ={"XDG_DATA_HOME": str(xdg_data_home)},
        home=tmp_path / "home",
    )

    assert path == xdg_data_home / "ArduPlaneTools"
    assert not xdg_data_home.exists()


def test_linux_uses_xdg_default_for_missing_or_relative_value(tmp_path):
    home = tmp_path / "home"

    missing = application_data_directory(
        platform_name="linux",
        environ={},
        home=home,
    )
    relative = application_data_directory(
        platform_name="linux",
        environ={"XDG_DATA_HOME": "relative/path"},
        home=home,
    )

    expected = home / ".local/share/ArduPlaneTools"
    assert missing == expected
    assert relative == expected
    assert not home.exists()


def test_default_store_paths_share_the_platform_application_directory():
    expected = application_data_directory()

    assert DEFAULT_STORE_PATH == expected / "battery_packs.json"
    assert BATTERY_HISTORY_PATH == expected / "battery_pack_history.json"
    assert RANGE_WALK_HISTORY_PATH == expected / "range_walk_history.json"
    assert DEFAULT_EVIDENCE_DIR == expected / "range_walk_csv"


def test_explicit_store_paths_remain_supported(tmp_path):
    pack_path = tmp_path / "packs.json"
    battery_history_path = tmp_path / "battery-history.json"
    range_history_path = tmp_path / "range-history.json"
    evidence_dir = tmp_path / "range-csv"

    pack_store = BatteryPackStore(pack_path)
    battery_history = BatteryPackHistoryStore(battery_history_path)
    range_history = RangeWalkHistoryStore(range_history_path, evidence_dir)

    assert pack_store.path == pack_path
    assert battery_history.path == battery_history_path
    assert range_history.path == range_history_path
    assert range_history.evidence_dir == evidence_dir
    assert not pack_path.exists()
    assert not battery_history_path.exists()
    assert not range_history_path.exists()
    assert not evidence_dir.exists()
