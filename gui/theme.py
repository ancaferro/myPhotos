"""Dark theme: palette, stylesheet, person colors and painted icons."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)

BG = "#14161a"
PANEL = "#1d2026"
PANEL_2 = "#23262d"
BORDER = "#31353d"
TEXT = "#e8eaed"
MUTED = "#9aa0a8"
ACCENT = "#4f8cff"
ACCENT_2 = "#6ea3ff"

# Golden-angle hue spacing gives every person a stable, distinct color.
GOLDEN_ANGLE = 137.508


def person_color(person_id, alpha=1.0):
    if person_id is None:
        color = QColor.fromHslF(220 / 360, 0.05, 0.63)
    else:
        color = QColor.fromHslF(((person_id * GOLDEN_ANGLE) % 360) / 360, 0.75, 0.58)
    color.setAlphaF(alpha)
    return color


def make_palette():
    pal = QPalette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        pal.setColor(group, QPalette.Window, QColor(BG))
        pal.setColor(group, QPalette.Base, QColor(BG))
        pal.setColor(group, QPalette.AlternateBase, QColor(PANEL))
        pal.setColor(group, QPalette.WindowText, QColor(TEXT))
        pal.setColor(group, QPalette.Text, QColor(TEXT))
        pal.setColor(group, QPalette.Button, QColor(PANEL_2))
        pal.setColor(group, QPalette.ButtonText, QColor(TEXT))
        pal.setColor(group, QPalette.ToolTipBase, QColor(PANEL_2))
        pal.setColor(group, QPalette.ToolTipText, QColor(TEXT))
        pal.setColor(group, QPalette.Highlight, QColor(ACCENT))
        pal.setColor(group, QPalette.HighlightedText, QColor("#ffffff"))
        pal.setColor(group, QPalette.PlaceholderText, QColor(MUTED))
    return pal


STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 14px; }}

#topbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
#brand {{ font-size: 18px; font-weight: 700; }}

QLineEdit {{
  background: {BG}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: 7px 12px; selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QPushButton#analyzeBtn {{
  background: {ACCENT}; color: #ffffff; font-weight: 600;
  border: none; border-radius: 8px; padding: 8px 22px;
}}
QPushButton#analyzeBtn:hover {{ background: {ACCENT_2}; }}
QPushButton#analyzeBtn:disabled {{ background: #3a4451; color: #c8ccd2; }}

QToolButton#browseBtn {{
  background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: 7px 12px;
}}
QToolButton#browseBtn:hover {{ border: 1px solid {ACCENT}; }}

#progressRow {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QProgressBar {{
  background: {PANEL_2}; border: none; border-radius: 4px;
  max-height: 8px; min-height: 8px; text-align: center;
}}
QProgressBar::chunk {{
  border-radius: 4px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 #7cc4ff);
}}
QLabel#progressLabel, QLabel#mutedLabel {{ color: {MUTED}; font-size: 12px; }}

QFrame#banner {{
  background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QFrame#banner QLabel {{ font-size: 13px; background: transparent; }}
QPushButton#linkBtn {{
  color: {ACCENT_2}; background: transparent; border: none;
  font-size: 13px; text-decoration: underline; padding: 0;
}}

QLabel#emptyState {{ color: {MUTED}; font-size: 15px; }}

#sidebar {{ background: {PANEL}; border-left: 1px solid {BORDER}; }}
QLabel#sidebarTitle {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}

QToolButton#actionBtn {{
  background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QToolButton#actionBtn:hover {{ border: 1px solid {ACCENT}; }}

QFrame#personRow {{ background: transparent; border: 1px solid transparent; border-radius: 8px; }}
QFrame#personRow:hover {{ background: {PANEL_2}; }}
QFrame#personRow[active="true"] {{ background: {PANEL_2}; border: 1px solid {ACCENT}; }}
QLabel#personCount {{ color: {MUTED}; font-size: 12px; background: transparent; }}
QToolButton#personBtn {{
  background: transparent; border: none; border-radius: 6px;
  color: {MUTED}; font-size: 13px;
}}
QToolButton#personBtn:hover {{ background: {BORDER}; color: {TEXT}; }}

QListView#gallery {{ background: {BG}; border: none; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a5058; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; }}

QToolButton#lightboxClose {{
  background: rgba(35, 38, 45, 0.78); color: {TEXT};
  border: 1px solid {BORDER}; border-radius: 18px; font-size: 16px;
}}
QToolButton#lightboxClose:hover {{ background: #2e3340; border: 1px solid {ACCENT}; }}
"""


def _painted_icon(draw, size=20):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(TEXT), 1.6))
    painter.setBrush(Qt.NoBrush)
    draw(painter)
    painter.end()
    return QIcon(pixmap)


def aspect_icon(key):
    """Portrait ("34") or landscape ("43") rounded rectangle."""
    if key == "34":
        rect = QRectF(5.5, 2.5, 9, 15)
    else:
        rect = QRectF(2.5, 5.5, 15, 9)
    return _painted_icon(lambda p: p.drawRoundedRect(rect, 1.5, 1.5))


def _paint_app_icon(p):
    """Camera glyph on an accent gradient tile, drawn on a 256x256 canvas."""
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    grad = QLinearGradient(0, 8, 0, 248)
    grad.setColorAt(0.0, QColor("#6ea3ff"))
    grad.setColorAt(1.0, QColor("#3567d6"))
    p.fillPath(tile, grad)

    body = QPainterPath()
    body.addRoundedRect(QRectF(40, 92, 176, 116), 22, 22)
    bump = QPainterPath()
    bump.addRoundedRect(QRectF(96, 68, 64, 40), 12, 12)
    p.fillPath(body.united(bump), QColor("#f4f6f9"))

    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#3567d6"))
    p.drawEllipse(QRectF(184, 106, 18, 18))
    p.setBrush(QColor("#1b2634"))
    p.drawEllipse(QPointF(128, 150), 42, 42)
    p.setBrush(QColor("#4f8cff"))
    p.drawEllipse(QPointF(128, 150), 30, 30)
    p.setBrush(QColor("#dbe7ff"))
    p.drawEllipse(QPointF(138, 140), 8, 8)


def app_icon():
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(size / 256, size / 256)
        _paint_app_icon(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def eye_icon(off=False):
    def draw(p):
        p.drawEllipse(QRectF(2, 5.5, 16, 9))
        p.drawEllipse(QRectF(7.5, 7.5, 5, 5))
        if off:
            p.drawLine(4, 17, 16, 3)

    return _painted_icon(draw)
