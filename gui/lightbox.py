"""Full-size photo overlay: zoom, pan, prev/next navigation, close button.

Interaction: mouse wheel zooms around the cursor, dragging pans a zoomed
photo, the side zones (or Left/Right arrow keys) switch photos, the ✕ button,
Esc or a click on the empty background closes the overlay.
"""

import logging
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QToolButton

from gui.facepaint import draw_face_boxes
from gui.thumbs import _read_image
from gui.theme import MUTED, TEXT

log = logging.getLogger(__name__)

CAPTION_H = 40
MAX_ZOOM = 12.0
DRAG_THRESHOLD = 4


class Lightbox(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._photos = []
        self._index = 0
        self._pixmap = None
        self.show_boxes = True
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._press_pos = None
        self._pan_start = QPointF(0, 0)
        self._dragged = False
        self._hover_zone = None

        self._close_btn = QToolButton(self)
        self._close_btn.setObjectName("lightboxClose")
        self._close_btn.setText("✕")
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self.accept)

    # ------------------------------------------------------------------ state

    def show_photos(self, photos, index, show_boxes=True):
        self._photos = photos
        self.show_boxes = show_boxes
        self.setGeometry(self.parentWidget().window().geometry())
        self._load(index)
        self.open()

    def _load(self, index):
        self._index = index
        image = _read_image(self._photos[index]["path"])
        if image.isNull():
            log.warning("could not read %s", self._photos[index]["path"])
        self._pixmap = None if image.isNull() else QPixmap.fromImage(image)
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._hover_zone = None
        self.update()

    @property
    def _photo(self):
        return self._photos[self._index]

    def _has_prev(self):
        return self._index > 0

    def _has_next(self):
        return self._index < len(self._photos) - 1

    # --------------------------------------------------------------- geometry

    def _fit_size(self):
        """Size of the photo at zoom 1 (fit into the window, never upscaled)."""
        max_w = self.width() * 0.88
        max_h = self.height() * 0.82 - CAPTION_H
        scale = min(max_w / self._pixmap.width(), max_h / self._pixmap.height(), 1.0)
        return QPointF(self._pixmap.width() * scale, self._pixmap.height() * scale)

    def _base_center(self):
        return QPointF(self.width() / 2, (self.height() - CAPTION_H) / 2)

    def _draw_rect(self):
        size = self._fit_size() * self._zoom
        center = self._base_center() + self._pan
        return QRectF(center.x() - size.x() / 2, center.y() - size.y() / 2,
                      size.x(), size.y())

    def _clamp_pan(self):
        size = self._fit_size() * self._zoom
        half_x = max(0.0, (size.x() - self.width()) / 2)
        half_y = max(0.0, (size.y() - self.height()) / 2)
        self._pan = QPointF(
            min(max(self._pan.x(), -half_x), half_x),
            min(max(self._pan.y(), -half_y), half_y),
        )

    def _zone_w(self):
        return max(80, min(140, self.width() // 8))

    def _zone_at(self, pos):
        if pos.x() < self._zone_w() and self._has_prev():
            return "left"
        if pos.x() > self.width() - self._zone_w() and self._has_next():
            return "right"
        return None

    # ------------------------------------------------------------ interaction

    def wheelEvent(self, event):
        if self._pixmap is None:
            return
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        new_zoom = min(max(self._zoom * (1.15 ** steps), 1.0), MAX_ZOOM)
        if new_zoom == self._zoom:
            return
        # Keep the image point under the cursor stationary while zooming.
        pos = event.position()
        center = self._draw_rect().center()
        ratio = new_zoom / self._zoom
        self._zoom = new_zoom
        self._pan = pos + (center - pos) * ratio - self._base_center()
        self._clamp_pan()
        self._update_cursor(pos)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position()
            self._pan_start = QPointF(self._pan)
            self._dragged = False

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._press_pos is not None:
            delta = pos - self._press_pos
            if abs(delta.x()) + abs(delta.y()) > DRAG_THRESHOLD:
                self._dragged = True
            if self._dragged and self._zoom > 1.0:
                self._pan = self._pan_start + delta
                self._clamp_pan()
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
            return
        zone = self._zone_at(pos)
        if zone != self._hover_zone:
            self._hover_zone = zone
            self.update()
        self._update_cursor(pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._press_pos is None:
            return
        pos = event.position()
        was_drag = self._dragged
        self._press_pos = None
        self._dragged = False
        self._update_cursor(pos)
        if was_drag:
            return
        zone = self._zone_at(pos)
        if zone == "left":
            self._load(self._index - 1)
        elif zone == "right":
            self._load(self._index + 1)
        elif self._pixmap is None or not self._draw_rect().contains(pos):
            self.accept()  # click on the empty background

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left and self._has_prev():
            self._load(self._index - 1)
        elif event.key() == Qt.Key_Right and self._has_next():
            self._load(self._index + 1)
        else:
            super().keyPressEvent(event)  # Esc closes

    def _update_cursor(self, pos):
        if self._zone_at(pos):
            self.setCursor(Qt.PointingHandCursor)
        elif self._zoom > 1.0 and self._draw_rect().contains(pos):
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._close_btn.move(self.width() - self._close_btn.width() - 16, 16)
        self._close_btn.raise_()

    # ---------------------------------------------------------------- painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(10, 11, 14, 235))
        if self._pixmap is None:
            painter.setPen(QColor(MUTED))
            font = painter.font()
            font.setPixelSize(15)
            painter.setFont(font)
            path = self._photo["path"] if self._photos else ""
            painter.drawText(
                self.rect(), Qt.AlignCenter, f"Could not load image\n{path}"
            )
            return

        dst = self._draw_rect()
        painter.drawPixmap(dst, self._pixmap, QRectF(self._pixmap.rect()))
        if self.show_boxes:
            photo = self._photo
            full = {"x": 0, "y": 0, "w": photo["width"], "h": photo["height"]}
            draw_face_boxes(painter, photo["faces"], full, dst, label_px=13)

        painter.setPen(QColor(MUTED))
        font = painter.font()
        font.setPixelSize(13)
        painter.setFont(font)
        caption = QRectF(16, self.height() - CAPTION_H, self.width() - 32, CAPTION_H)
        text = self._photo["path"]
        taken = self._photo.get("taken_at")
        if taken:
            text += f" · {datetime.fromtimestamp(taken):%Y-%m-%d %H:%M}"
        if len(self._photos) > 1:
            text = f"{self._index + 1} / {len(self._photos)}   {text}"
        painter.drawText(caption, Qt.AlignCenter, text)

        if self._has_prev():
            self._paint_arrow(painter, "left")
        if self._has_next():
            self._paint_arrow(painter, "right")

    def _paint_arrow(self, painter, side):
        cy = (self.height() - CAPTION_H) / 2
        cx = 44 if side == "left" else self.width() - 44
        hovered = self._hover_zone == side
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(29, 32, 38, 230 if hovered else 150))
        painter.drawEllipse(QPointF(cx, cy), 26, 26)
        painter.setPen(QColor(TEXT))
        font = painter.font()
        font.setPixelSize(28)
        painter.setFont(font)
        glyph = "‹" if side == "left" else "›"
        painter.drawText(QRectF(cx - 26, cy - 28, 52, 52), Qt.AlignCenter, glyph)
