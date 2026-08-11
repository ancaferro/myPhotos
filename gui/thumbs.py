"""Background image loading: gallery thumbnails and person portraits.

Workers decode with QImageReader (EXIF auto-transform, matching the
orientation the analyzer stored coordinates in) and hand QImages to the GUI
thread through signals; pixmaps are created and cached there.
"""

import logging
import os
import threading

from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

from gui.data import PORTRAIT_SIZE, THUMB_MAX, face_portrait_source
from paths import data_dir

log = logging.getLogger(__name__)

# Upper bound for the on-disk thumbnail cache. The cache key changes whenever a
# photo's mtime, aspect or crop changes, so entries are naturally superseded;
# without a budget the superseded ones (and those of photos no longer in the
# library) would stay on disk forever. Least-recently-used files are dropped
# first — a discarded thumbnail only costs one re-decode.
MAX_CACHE_BYTES = 512 * 1024 * 1024
# Trimming scans the directory, so it is not worth doing on every single write.
TRIM_EVERY_WRITES = 200


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
        self._cache_dir = os.path.join(data_dir(), "thumbs_cache")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._thumb_done.connect(self._on_thumb_done)
        self._portrait_done.connect(self._on_portrait_done)
        # Writes happen on pool threads; the counter and the trim are guarded.
        self._cache_lock = threading.Lock()
        # Primed so the first write of the session also trims, which is what
        # collects entries orphaned by edits made while the app was closed.
        self._writes_since_trim = TRIM_EVERY_WRITES

    def _cache_path(self, photo, aspect_key):
        """Disk-cache location; the key invalidates on file change (mtime),
        aspect switch and crop change (faces edited or deleted)."""
        crop = photo["crop"]
        key = (
            f"{photo['id']}-{int(photo.get('mtime') or 0)}-{aspect_key}"
            f"-{crop['x']}x{crop['y']}x{crop['w']}x{crop['h']}"
        )
        return os.path.join(self._cache_dir, key + ".jpg")

    # ------------------------------------------------------------- disk cache

    def _cache_entries(self):
        """(path, size, last_use) for every file in the cache directory."""
        entries = []
        try:
            with os.scandir(self._cache_dir) as it:
                for entry in it:
                    try:
                        if entry.is_file():
                            stat = entry.stat()
                            entries.append((entry.path, stat.st_size, stat.st_mtime))
                    except OSError:  # vanished mid-scan
                        continue
        except OSError:
            log.exception("could not read thumbnail cache %s", self._cache_dir)
        return entries

    def cache_size(self):
        """Total bytes currently held by the on-disk thumbnail cache."""
        return sum(size for _path, size, _used in self._cache_entries())

    def clear_cache(self):
        """Delete every cached thumbnail. Returns the number of bytes freed."""
        freed = 0
        with self._cache_lock:
            for path, size, _used in self._cache_entries():
                try:
                    os.remove(path)
                    freed += size
                except OSError:
                    log.warning("could not remove cached thumbnail %s", path)
            self._writes_since_trim = 0
        return freed

    def _touch(self, path):
        """Mark a cache hit; mtime doubles as the last-use time for eviction."""
        try:
            os.utime(path, None)
        except OSError:  # best-effort — a stale mtime only skews eviction order
            pass

    def _note_write(self):
        """Count a cache write and trim when enough have piled up."""
        with self._cache_lock:
            self._writes_since_trim += 1
            if self._writes_since_trim < TRIM_EVERY_WRITES:
                return
            self._writes_since_trim = 0
            self._trim_locked()

    def _trim_locked(self):
        """Drop least-recently-used files until under MAX_CACHE_BYTES."""
        entries = self._cache_entries()
        total = sum(size for _path, size, _used in entries)
        if total <= MAX_CACHE_BYTES:
            return
        entries.sort(key=lambda e: e[2])  # oldest last-use first
        removed = 0
        for path, size, _used in entries:
            if total <= MAX_CACHE_BYTES:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            total -= size
            removed += 1
        log.info(
            "trimmed thumbnail cache: removed %d files, now %.1f MiB",
            removed, total / 1024 / 1024,
        )

    # ------------------------------------------------------------- thumbnails

    def thumbnail(self, photo, aspect_key):
        """Cached pixmap, or None (and schedule a load) if not ready yet."""
        key = (photo["id"], aspect_key)
        pixmap = self._thumbs.get(key)
        if pixmap is None and key not in self._pending:
            self._pending.add(key)
            path, crop = photo["path"], dict(photo["crop"])
            cache = self._cache_path(photo, aspect_key)
            self._pool.start(_Job(lambda: self._load_thumb(key, path, crop, cache)))
        return pixmap

    def _load_thumb(self, key, path, crop, cache):
        image = QImage(cache) if os.path.exists(cache) else QImage()
        if image.isNull():
            image = _read_image(path)
            if image.isNull():
                log.warning("could not read thumbnail source %s", path)
            else:
                image = image.copy(QRect(crop["x"], crop["y"], crop["w"], crop["h"]))
                image = image.scaled(
                    QSize(*THUMB_MAX[key[1]]),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                if image.save(cache, "JPG", 85):
                    self._note_write()
                else:
                    log.warning("could not write thumbnail cache %s", cache)
        else:
            self._touch(cache)
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
