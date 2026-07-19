"""myPhotos — face cataloging desktop app (PySide6 + OpenCV + SQLite)."""

import sys

from PySide6.QtWidgets import QApplication

from database import init_db
from gui.theme import STYLESHEET, app_icon, make_palette
from gui.window import MainWindow

__version__ = "1.0.1"


def main():
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
