"""Executable PySide6 entry point for the ArduPlaneTools desktop shell."""

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from gui import MainWindow


PACKAGING_SMOKE_ARGUMENT = "--packaging-smoke"


def _run_packaging_smoke(arguments: list[str]) -> int:
    """Run the explicitly gated frozen-runtime check without starting Qt."""
    if len(arguments) != 3:
        return 2
    from gui.packaging_smoke import run_packaging_smoke

    return run_packaging_smoke(*(Path(value) for value in arguments))


def main(argv=None) -> int:
    """Start the native Qt event loop and show the desktop shell."""
    arguments = list(argv if argv is not None else sys.argv)
    if arguments[1:2] == [PACKAGING_SMOKE_ARGUMENT]:
        return _run_packaging_smoke(arguments[2:])
    app = QApplication(arguments)
    app.setApplicationName("ArduPlaneTools")
    app.setOrganizationName("ArduPlaneTools")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
