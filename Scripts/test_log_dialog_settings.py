"""Tests for the persisted native BIN dialog directory."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog

from gui import MainWindow
from gui import log_dialog_settings as settings


def test_dialog_directory_survives_restart_and_cancel(monkeypatch, tmp_path, qt_app):
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(settings, "QSettings", lambda *_args: QSettings(str(ini), QSettings.Format.IniFormat))
    log = tmp_path / "logs" / "flight.bin"
    log.parent.mkdir()
    log.touch()
    starts = []
    def choose(*args):
        starts.append(args[2])
        return (str(log), "") if len(starts) == 1 else ("", "")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose)
    first = MainWindow()
    first.choose_log()
    first.close()
    second = MainWindow()
    second.choose_log()
    second.close()
    assert starts[1] == str(log.parent)
    assert settings.starting_directory() == log.parent


def test_missing_saved_directory_uses_platform_fallback(monkeypatch, tmp_path):
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(settings, "QSettings", lambda *_args: QSettings(str(ini), QSettings.Format.IniFormat))
    QSettings(str(ini), QSettings.Format.IniFormat).setValue(settings.SETTING_KEY, str(tmp_path / "gone"))
    monkeypatch.setattr(settings.sys, "platform", "darwin")
    assert settings.starting_directory() == Path.home() / "ArduPilotTools"
    monkeypatch.setattr(settings.sys, "platform", "win32")
    monkeypatch.setattr(settings.QStandardPaths, "writableLocation", lambda *_args: str(tmp_path / "Documents"))
    assert settings.starting_directory() == tmp_path / "Documents"
