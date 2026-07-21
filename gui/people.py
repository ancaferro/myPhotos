"""People sidebar: avatar rows with filter, rename, merge and delete."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import person_color

AVATAR = 44


def _circular_avatar(pixmap, color):
    """Avatar pixmap cropped to a circle with a 2px person-colored ring."""
    result = QPixmap(AVATAR, AVATAR)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    if pixmap is not None:
        path = QPainterPath()
        path.addEllipse(QRectF(1, 1, AVATAR - 2, AVATAR - 2))
        painter.setClipPath(path)
        painter.drawPixmap(result.rect(), pixmap)
        painter.setClipping(False)
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(1, 1, AVATAR - 2, AVATAR - 2))
    painter.end()
    return result


class PersonRow(QFrame):
    clicked = Signal(int)
    rename_requested = Signal(dict)
    merge_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, person, active, parent=None):
        super().__init__(parent)
        self.person = person
        self.setObjectName("personRow")
        self.setProperty("active", "true" if active else "false")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.avatar = QLabel()
        self.avatar.setFixedSize(AVATAR, AVATAR)
        self.set_portrait(None)
        layout.addWidget(self.avatar)

        meta = QVBoxLayout()
        meta.setSpacing(1)
        name = QLabel(person["name"])
        name.setStyleSheet(
            f"color: {person_color(person['id']).name()};"
            " font-size: 14px; font-weight: 600; background: transparent;"
        )
        count = QLabel(
            f"{person['photo_count']} photo{'' if person['photo_count'] == 1 else 's'}"
        )
        count.setObjectName("personCount")
        meta.addWidget(name)
        meta.addWidget(count)
        layout.addLayout(meta, 1)

        self._buttons = QWidget()
        self._buttons.setStyleSheet("background: transparent;")
        buttons = QHBoxLayout(self._buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(2)
        for text, tip, signal in (
            ("✎", "Rename", self.rename_requested),
            ("⇆", "Merge into another person", self.merge_requested),
            ("\U0001f5d1", "Delete person and its face boxes", self.delete_requested),
        ):
            btn = QToolButton()
            btn.setObjectName("personBtn")
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, s=signal: s.emit(self.person))
            buttons.addWidget(btn)
        layout.addWidget(self._buttons)
        self._buttons.setVisible(active)
        self._active = active

    def set_portrait(self, pixmap):
        self.avatar.setPixmap(_circular_avatar(pixmap, person_color(self.person["id"])))

    def enterEvent(self, event):
        self._buttons.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._buttons.setVisible(self._active)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.person["id"])
        super().mousePressEvent(event)


class PeoplePanel(QWidget):
    """Scrollable list of PersonRow widgets; rebuilt from list_persons() data."""

    person_clicked = Signal(int)
    rename_requested = Signal(dict)
    merge_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, loader, parent=None):
        super().__init__(parent)
        self._loader = loader
        self._rows = []
        self._persons = []
        self._active_ids = set()
        loader.portrait_ready.connect(self._on_portrait_ready)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 4, 0)
        self._list.setSpacing(2)
        self._list.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self.empty = QLabel("No people detected yet.")
        self.empty.setObjectName("mutedLabel")
        outer.addWidget(self.empty)

    def persons(self):
        return self._persons

    def rebuild(self, persons, active_ids):
        active_ids = set(active_ids)
        if persons == self._persons and active_ids == self._active_ids:
            return
        self._persons = persons
        self._active_ids = active_ids
        for row in self._rows:
            self._list.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        for person in persons:
            row = PersonRow(person, active=person["id"] in active_ids)
            row.clicked.connect(self.person_clicked)
            row.rename_requested.connect(self.rename_requested)
            row.merge_requested.connect(self.merge_requested)
            row.delete_requested.connect(self.delete_requested)
            pixmap = self._loader.portrait(person["portrait_face_id"])
            if pixmap is not None:
                row.set_portrait(pixmap)
            self._list.insertWidget(self._list.count() - 1, row)
            self._rows.append(row)

        self.empty.setVisible(not persons)

    def _on_portrait_ready(self, face_id):
        for row in self._rows:
            if row.person["portrait_face_id"] == face_id:
                pixmap = self._loader.portrait(face_id)
                if pixmap is not None:
                    row.set_portrait(pixmap)
