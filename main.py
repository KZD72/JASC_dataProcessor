"""Application entry point."""

from __future__ import annotations

import logging
import multiprocessing
import sys


def setup_logging() -> None:
    """Configure process-wide console logging for the desktop app."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> int:
    """Start the Qt application."""
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("JASC Data Processor")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
