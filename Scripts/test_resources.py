"""Focused tests for installation-safe read-only resource lookup."""

import os
import sys

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.config import Config
from core.resources import application_resource_root, resource_path


def test_source_resources_are_independent_of_current_working_directory(
    monkeypatch,
    tmp_path,
):
    expected_root = application_resource_root()
    monkeypatch.chdir(tmp_path)

    config = Config("Config/landing.yaml")

    assert application_resource_root() == expected_root
    assert config.filename == expected_root / "Config/landing.yaml"
    assert config.get("analysis") is not None
    assert resource_path("Docs/gui_help/events/README.md").is_file()


def test_absolute_config_path_preserves_existing_api(tmp_path):
    path = tmp_path / "custom.yaml"
    path.write_text("answer: 42\n", encoding="utf-8")

    config = Config(path)

    assert config.filename == path
    assert config.get("answer") == 42


def test_simulated_frozen_root_finds_config_and_gui_markdown(
    monkeypatch,
    tmp_path,
    qt_app,
):
    pytest.importorskip("PySide6")
    from gui.docs_viewer import ModuleDocsWindow

    config_directory = tmp_path / "Config"
    config_directory.mkdir()
    (config_directory / "packaged.yaml").write_text(
        "analysis:\n  name: packaged\n",
        encoding="utf-8",
    )
    docs_directory = tmp_path / "Docs/gui_help/events"
    docs_directory.mkdir(parents=True)
    (docs_directory / "README.md").write_text(
        "# Packaged Events\n\nBundled README evidence.\n",
        encoding="utf-8",
    )
    (docs_directory / "glossary.md").write_text(
        "# Packaged Events glossary\n\nBundled glossary evidence.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    config = Config("Config/packaged.yaml")
    viewer = ModuleDocsWindow("Events")
    viewer.show()
    qt_app.processEvents()

    assert application_resource_root() == tmp_path
    assert config.filename == tmp_path / "Config/packaged.yaml"
    assert config.get("analysis.name") == "packaged"
    assert viewer.docs_root == tmp_path / "Docs/gui_help"
    assert "Bundled README evidence" in viewer.readme_browser.toPlainText()
    assert "Bundled glossary evidence" in viewer.glossary_browser.toPlainText()
    viewer.close()
    qt_app.processEvents()


def test_frozen_process_without_resource_root_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    with pytest.raises(
        RuntimeError,
        match="Frozen application resource root is unavailable",
    ):
        resource_path("Config/landing.yaml")
