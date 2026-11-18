"""Tags sidebar: colored tag rows with filtering, rename and delete."""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import tag_color

DOT = 12
# The panel hugs its content and sits at the bottom of the sidebar, so it grows
# upwards as tags are added; past this many rows it starts scrolling instead.
MAX_VISIBLE_ROWS = 7


def _dot_pixmap(color):
    pixmap = QPixmap(DOT, DOT)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(0.5, 0.5, DOT - 1, DOT - 1))
    painter.end()
    return pixmap


class TagRow(QFrame):
    clicked = Signal(int)
    rename_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, tag, active, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.setObjectName("personRow")  # shares the sidebar row styling
        self.setProperty("active", "true" if active else "false")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        dot = QLabel()
        dot.setPixmap(_dot_pixmap(tag_color(tag["id"])))
        dot.setFixedSize(DOT, DOT)
        layout.addWidget(dot)

        name = QLabel(tag["name"])
        name.setStyleSheet(
            f"color: {tag_color(tag['id']).name()}; font-size: 13px;"
            " font-weight: 600; background: transparent;"
        )
        layout.addWidget(name, 1)

        count = QLabel(str(tag["photo_count"]))
        count.setObjectName("personCount")
        layout.addWidget(count)

        self._buttons = QWidget()
        self._buttons.setStyleSheet("background: transparent;")
        buttons = QHBoxLayout(self._buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(2)
        for text, tip, signal in (
            ("✎", "Rename tag", self.rename_requested),
            ("\U0001f5d1", "Delete tag", self.delete_requested),
        ):
            btn = QToolButton()
            btn.setObjectName("personBtn")
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, s=signal: s.emit(self.tag))
            buttons.addWidget(btn)
        layout.addWidget(self._buttons)
        self._active = active
        self._buttons.setVisible(active)

    def enterEvent(self, event):
        self._buttons.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._buttons.setVisible(self._active)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.tag["id"])
        super().mousePressEvent(event)


class TagsPanel(QWidget):
    """Tag rows anchored to the bottom of the sidebar.

    The panel asks for exactly the height its rows need, so each new tag
    pushes the list one row further up; beyond MAX_VISIBLE_ROWS it scrolls.
    """

    tag_clicked = Signal(int)
    rename_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._tags = []
        self._active_ids = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 4, 0)
        self._list.setSpacing(2)
        self._scroll.setWidget(inner)
        outer.addWidget(self._scroll)

        self.empty = QLabel("No tags yet. Right-click a photo to add one.")
        self.empty.setObjectName("mutedLabel")
        self.empty.setWordWrap(True)
        outer.addWidget(self.empty)

        self._scroll.hide()  # nothing to show until the first tag exists
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def sizeHint(self):
        """Height of the visible rows (capped), or of the empty-state hint."""
        width = super().sizeHint().width()
        if not self._rows:
            return QSize(width, self.empty.sizeHint().height())
        rows = min(len(self._rows), MAX_VISIBLE_ROWS)
        row_h = self._rows[0].sizeHint().height()
        spacing = self._list.spacing()
        return QSize(width, rows * row_h + (rows - 1) * spacing + 2)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def tags(self):
        return self._tags

    def rebuild(self, tags, active_ids):
        active_ids = set(active_ids)
        if tags == self._tags and active_ids == self._active_ids:
            return
        self._tags = tags
        self._active_ids = active_ids
        for row in self._rows:
            self._list.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        for tag in tags:
            row = TagRow(tag, active=tag["id"] in active_ids)
            row.clicked.connect(self.tag_clicked)
            row.rename_requested.connect(self.rename_requested)
            row.delete_requested.connect(self.delete_requested)
            self._list.addWidget(row)
            self._rows.append(row)

        self.empty.setVisible(not tags)
        self._scroll.setVisible(bool(tags))
        self.updateGeometry()  # the panel's height follows the row count
