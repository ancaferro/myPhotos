"""myPhotos — face cataloging desktop app (PySide6 + OpenCV + SQLite)."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication, QMessageBox

from database import init_db
from gui.theme import STYLESHEET, app_icon, make_palette
from gui.window import MainWindow
from paths import data_dir, is_frozen

__version__ = "1.0.2"

log = logging.getLogger(__name__)


def setup_logging():
    """Console logging always; a rotating log file for frozen builds.

    Packaged executables run windowed (no console), so the file in the data
    dir is the only way to debug them.
    """
    handlers = [logging.StreamHandler()]
    if is_frozen():
        handlers.append(
            RotatingFileHandler(
                os.path.join(data_dir(), "myphotos.log"),
                maxBytes=1_000_000,
                backupCount=1,
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def excepthook(exc_type, exc, tb):
    """Log unhandled exceptions and tell the user instead of dying silently."""
    log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    if QApplication.instance() is not None:
        QMessageBox.critical(None, "myPhotos", f"Unexpected error:\n{exc}")


def main():
    setup_logging()
    sys.excepthook = excepthook
    log.info("myPhotos %s starting", __version__)
    init_db()
    app = QApplication(sys.argv)
    app.setOrganizationName("myPhotos")
    app.setApplicationName("myPhotos")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setPalette(make_palette())
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
