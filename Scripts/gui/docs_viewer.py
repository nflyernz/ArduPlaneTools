"""Local Markdown documentation viewer for GUI analysis modules."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.resources import resource_path


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

DOCS_ROOT = resource_path("Docs/gui_help")
PROCEDURE_MODULES = frozenset(("Radio Link", "Range-Walk Comparison", "Stall"))


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return (
            "# Documentation unavailable\n\n"
            f"Unable to read `{path}`.\n\n"
            f"{exc}"
        )


def _markdown_browser(path: Path, object_name: str) -> QTextBrowser:
    """Create the established read-only Markdown presentation surface."""
    browser = QTextBrowser()
    browser.setObjectName(object_name)
    browser.setOpenExternalLinks(False)
    document = browser.document()
    document.setBaseUrl(path.parent.as_uri() + "/")
    body_font = browser.font()
    body_font.setPointSizeF(body_font.pointSizeF() + 2.0)
    document.setDefaultFont(body_font)
    browser.setMarkdown(_read_markdown(path))
    return browser


class ModuleDocsWindow(QWidget):
    """Resizable, non-modal README and glossary viewer for one module."""

    def __init__(self, module: str, parent=None, docs_root: Path | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.module = module
        self.docs_root = (
            Path(docs_root)
            if docs_root is not None
            else resource_path("Docs/gui_help")
        )
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
        browser = _markdown_browser(path, f"{label.lower()}Browser")
        self.tabs.addTab(browser, label)
        return browser


class ProcedureWindow(QWidget):
    """Resizable, non-modal viewer for one module's test procedure."""

    def __init__(self, module: str, parent=None, docs_root: Path | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.module = module
        root = (
            Path(docs_root)
            if docs_root is not None
            else resource_path("Docs/gui_help")
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"{module} Test Procedure — ArduPlaneTools")
        self.setMinimumSize(620, 460)
        self.resize(820, 650)
        path = root / MODULE_SLUGS[module] / "procedure.md"
        layout = QVBoxLayout(self)
        self.browser = _markdown_browser(path, "procedureBrowser")
        layout.addWidget(self.browser)


class DocumentationController:
    """Own module documentation and procedure buttons and windows."""

    def __init__(self, parent):
        self.parent = parent
        self.docs_buttons: dict[str, QPushButton] = {}
        self.procedure_buttons: dict[str, QPushButton] = {}
        self.docs_windows: dict[str, ModuleDocsWindow] = {}
        self.procedure_windows: dict[str, ProcedureWindow] = {}

    def add_buttons(self, module: str, layout: QHBoxLayout) -> None:
        """Add established Docs and any module-specific procedure action."""
        docs_button = QPushButton("Docs")
        docs_button.setObjectName(
            f"{module.lower().replace(' ', '_').replace('-', '_')}DocsButton"
        )
        docs_button.clicked.connect(
            lambda _checked=False, name=module: self.open_docs(name)
        )
        layout.addWidget(docs_button)
        self.docs_buttons[module] = docs_button
        if module in PROCEDURE_MODULES:
            procedure_button = QPushButton("Test Procedure")
            procedure_button.setObjectName(
                f"{module.lower().replace(' ', '_')}TestProcedureButton"
            )
            procedure_button.clicked.connect(
                lambda _checked=False, name=module: self.open_procedure(name)
            )
            layout.addWidget(procedure_button)
            self.procedure_buttons[module] = procedure_button

    def open_docs(self, module: str) -> None:
        self._open_retained(
            module,
            self.docs_windows,
            lambda: ModuleDocsWindow(module, self.parent),
        )

    def open_procedure(self, module: str) -> None:
        self._open_retained(
            module,
            self.procedure_windows,
            lambda: ProcedureWindow(module, self.parent),
        )

    def close_all(self) -> None:
        windows = (*self.docs_windows.values(), *self.procedure_windows.values())
        self.docs_windows.clear()
        self.procedure_windows.clear()
        for window in windows:
            window.close()

    @staticmethod
    def _open_retained(module, windows, factory) -> None:
        existing = windows.get(module)
        if existing is not None:
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return
        viewer = factory()
        viewer.destroyed.connect(
            lambda _object=None, name=module: windows.pop(name, None)
        )
        windows[module] = viewer
        viewer.show()
