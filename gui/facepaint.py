"""Painting of face rectangles with person-colored name labels."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen

from gui.theme import person_color


def draw_face_boxes(painter, faces, src, dst, label_px=10):
    """Draw face boxes over an image drawn at dst.

    src is the visible window in original-image coordinates (a dict with
    x/y/w/h): the fixed-aspect thumbnail crop for cards, or the whole image
    for the lightbox. dst is the QRectF the image occupies on screen.
    """
    if not faces:
        return
    sx = dst.width() / src["w"]
    sy = dst.height() / src["h"]

    painter.save()
    painter.setClipRect(dst, Qt.IntersectClip)
    font = painter.font()
    font.setPixelSize(label_px)
    font.setWeight(font.Weight.DemiBold)
    painter.setFont(font)
    metrics = painter.fontMetrics()

    for f in faces:
        rect = QRectF(
            dst.x() + (f["x"] - src["x"]) * sx,
            dst.y() + (f["y"] - src["y"]) * sy,
            f["w"] * sx,
            f["h"] * sy,
        )
        border = person_color(f["person_id"])
        painter.setPen(QPen(border, 2))
        painter.setBrush(person_color(f["person_id"], 0.24))
        painter.drawRoundedRect(rect, 4, 4)

        name = f["person_name"] or "Unknown"
        label = QRectF(
            rect.x() - 1,
            rect.y() - 1,
            metrics.horizontalAdvance(name) + 12,
            metrics.height() + 4,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(person_color(f["person_id"], 0.85))
        painter.drawRoundedRect(label, 3, 3)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(label, Qt.AlignCenter, name)

    painter.restore()
