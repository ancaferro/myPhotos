"""Render the app icon to assets/icon.ico (used by the PyInstaller build)."""

import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap  # noqa: E402

from gui.theme import _paint_app_icon  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SIZES = [16, 32, 48, 64, 128, 256]


def main():
    QGuiApplication(sys.argv)
    os.makedirs(ASSETS, exist_ok=True)

    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    _paint_app_icon(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QBuffer.ReadWrite)
    pixmap.save(buffer, "PNG")
    image = Image.open(io.BytesIO(bytes(buffer.data())))

    ico = os.path.join(ASSETS, "icon.ico")
    image.save(ico, sizes=[(s, s) for s in SIZES])
    print(f"wrote {ico}")


if __name__ == "__main__":
    main()
