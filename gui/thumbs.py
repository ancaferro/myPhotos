"""Background image loading: gallery thumbnails and person portraits.

Workers decode with QImageReader (EXIF auto-transform, matching the
orientation the analyzer stored coordinates in) and hand QImages to the GUI
thread through signals; pixmaps are created and cached there.
"""

import logging

from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

from gui.data import PORTRAIT_SIZE, THUMB_MAX, face_portrait_source

log = logging.getLogger(__name__)


def _read_image(path):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    return reader.read()  # null QImage on failure


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self._fn()
        except Exception:  # noqa: BLE001 - keep the thread pool alive
            log.exception("image loader job failed")


class ImageLoader(QObject):
    """Async loader with in-memory caches keyed by photo/face ids."""

    _thumb_done = Signal(int, str, QImage)
    _portrait_done = Signal(int, QImage)
    thumb_ready = Signal(int, str)  # photo_id, aspect_key
    portrait_ready = Signal(int)  # face_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._thumbs = {}  # (photo_id, aspect_key) -> QPixmap
        self._portraits = {}  # face_id -> QPixmap
        self._pending = set()
        self._thumb_done.connect(self._on_thumb_done)
        self._portrait_done.connect(self._on_portrait_done)

    # ------------------------------------------------------------- thumbnails

    def thumbnail(self, photo, aspect_key):
        """Cached pixmap, or None (and schedule a load) if not ready yet."""
        key = (photo["id"], aspect_key)
        pixmap = self._thumbs.get(key)
        if pixmap is None and key not in self._pending:
            self._pending.add(key)
            path, crop = photo["path"], dict(photo["crop"])
            self._pool.start(_Job(lambda: self._load_thumb(key, path, crop)))
        return pixmap

    def _load_thumb(self, key, path, crop):
        image = _read_image(path)
        if image.isNull():
            log.warning("could not read thumbnail source %s", path)
        else:
            image = image.copy(QRect(crop["x"], crop["y"], crop["w"], crop["h"]))
            image = image.scaled(
                QSize(*THUMB_MAX[key[1]]), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self._thumb_done.emit(key[0], key[1], image)

    def _on_thumb_done(self, photo_id, aspect_key, image):
        key = (photo_id, aspect_key)
        self._pending.discard(key)
        if not image.isNull():
            self._thumbs[key] = QPixmap.fromImage(image)
            self.thumb_ready.emit(photo_id, aspect_key)

    # -------------------------------------------------------------- portraits

    def portrait(self, face_id):
        """Cached avatar pixmap, or None (and schedule a load) if not ready."""
        if face_id is None:
            return None
        pixmap = self._portraits.get(face_id)
        if pixmap is None and ("face", face_id) not in self._pending:
            self._pending.add(("face", face_id))
            self._pool.start(_Job(lambda: self._load_portrait(face_id)))
        return pixmap

    def _load_portrait(self, face_id):
        try:
            row = face_portrait_source(face_id)
        except Exception:  # noqa: BLE001 - a broken DB must not kill the worker
            log.exception("loading portrait source for face %s failed", face_id)
            row = None
        image = _read_image(row["path"]) if row else QImage()
        if image.isNull() and row is not None:
            log.warning("could not read portrait source %s", row["path"])
        if not image.isNull():
            # Square crop around the face with a 30% margin, clamped to the image.
            cx, cy = row["x"] + row["w"] / 2, row["y"] + row["h"] / 2
            side = max(row["w"], row["h"]) * 1.3
            x1 = max(0, int(cx - side / 2))
            y1 = max(0, int(cy - side / 2))
            x2 = min(image.width(), int(cx + side / 2))
            y2 = min(image.height(), int(cy + side / 2))
            image = image.copy(QRect(x1, y1, x2 - x1, y2 - y1))
            image = image.scaled(
                PORTRAIT_SIZE, PORTRAIT_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self._portrait_done.emit(face_id, image)

    def _on_portrait_done(self, face_id, image):
        self._pending.discard(("face", face_id))
        if not image.isNull():
            self._portraits[face_id] = QPixmap.fromImage(image)
            self.portrait_ready.emit(face_id)

    def is_idle(self):
        return not self._pending
