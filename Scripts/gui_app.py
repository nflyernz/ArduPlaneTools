"""Executable PySide6 entry point for the ArduPlaneTools desktop shell."""

import sys

from PySide6.QtWidgets import QApplication

from gui import MainWindow


def main(argv=None) -> int:
    """Start the native Qt event loop and show the desktop shell."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ArduPlaneTools")
    app.setOrganizationName("ArduPlaneTools")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
