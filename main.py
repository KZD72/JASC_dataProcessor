"""Application entry point."""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys


def setup_logging() -> None:
    """Configure process-wide console logging for the desktop app."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main(arguments: list[str] | None = None) -> int:
    """Start the GUI or the shared restricted recording runner."""
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments and arguments[0] in {"--run-script", "--script-worker"}:
        from core.script_cli import main as script_main, worker_main
        return (worker_main if arguments[0] == "--script-worker" else script_main)(arguments[1:])
    smoke = arguments == ["--self-test"]
    if smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("JASC Data Processor")

    window = MainWindow()
    window.show()

    if smoke:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, window.close)

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
