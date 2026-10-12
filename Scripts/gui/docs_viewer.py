"""Local Markdown documentation viewer for GUI analysis modules."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget, QTextBrowser, QVBoxLayout, QWidget


MODULE_SLUGS = {
    "Landing": "landing",
    "Events": "events",
    "Battery": "battery",
    "Battery Pack Management": "battery_pack_management",
    "Pack Performance": "pack_performance",
    "TAKEOFF": "takeoff",
    "AUTOTUNE": "autotune",
    "Radio Link": "radio_link",
    "Range-Walk Comparison": "range_walk_comparison",
    "Stall": "stall",
}

DOCS_ROOT = Path(__file__).resolve().parents[2] / "Docs" / "gui_help"


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return (
            "# Documentation unavailable\n\n"
            f"Unable to read `{path}`.\n\n"
            f"{exc}"
        )


class ModuleDocsWindow(QWidget):
    """Resizable, non-modal README and glossary viewer for one module."""

    def __init__(self, module: str, parent=None, docs_root: Path | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.module = module
        self.docs_root = Path(docs_root) if docs_root is not None else DOCS_ROOT
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"{module} Documentation — ArduPlaneTools")
        self.setMinimumSize(620, 460)
        self.resize(820, 650)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        module_directory = self.docs_root / MODULE_SLUGS[module]
        self.readme_browser = self._add_document_tab(
            "README", module_directory / "README.md"
        )
        self.glossary_browser = self._add_document_tab(
            "Glossary", module_directory / "glossary.md"
        )

    def _add_document_tab(self, label: str, path: Path) -> QTextBrowser:
        browser = QTextBrowser()
        browser.setObjectName(f"{label.lower()}Browser")
        browser.setOpenExternalLinks(False)
        document = browser.document()
        document.setBaseUrl(path.parent.as_uri() + "/")
        body_font = browser.font()
        body_font.setPointSizeF(body_font.pointSizeF() + 2.0)
        document.setDefaultFont(body_font)
        browser.setMarkdown(_read_markdown(path))
        self.tabs.addTab(browser, label)
        return browser
