"""Photo grid: list model, card delegate and the gallery view.

The grid always shows COLUMNS columns: cell size is recomputed from the
viewport width on every resize, so cards scale with the window.
"""

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from gui.data import THUMB_ASPECTS
from gui.facepaint import draw_face_boxes
from gui.theme import ACCENT, BORDER, MUTED, PANEL

DEFAULT_COLUMNS = 4
GAP = 12  # gutter between cards (GAP/2 inset on every cell side)
FILENAME_BAR = 30
RADIUS = 10


class PhotoModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._photos = []

    def set_photos(self, photos):
        self.beginResetModel()
        self._photos = photos
        self.endResetModel()

    def photos(self):
        return self._photos

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._photos)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.UserRole and index.isValid():
            return self._photos[index.row()]
        return None


class PhotoDelegate(QStyledItemDelegate):
    """Card with a fixed-aspect face-centered thumbnail, face boxes, filename."""

    def __init__(self, loader, parent=None):
        super().__init__(parent)
        self._loader = loader
        self.aspect_key = "34"
        self.show_boxes = True
        self.cell_size = QSize(240, 350)  # replaced by GalleryView._update_grid()

    def sizeHint(self, option, index):
        return self.cell_size

    def paint(self, painter, option, index):
        photo = index.data(Qt.UserRole)
        if photo is None:
            return
        half = GAP // 2
        card = option.rect.adjusted(half, half, -half, -half)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(card), RADIUS, RADIUS)
        painter.setClipPath(clip)
        painter.fillRect(card, QColor(PANEL))

        frame = QRect(card.x(), card.y(), card.width(), card.height() - FILENAME_BAR)
        painter.fillRect(frame, QColor("#000000"))
        pixmap = self._loader.thumbnail(photo, self.aspect_key)
        if pixmap is not None:
            painter.drawPixmap(frame, pixmap)
        if self.show_boxes:
            draw_face_boxes(painter, photo["faces"], photo["crop"], QRectF(frame))

        name_rect = QRect(card.x() + 10, frame.bottom(), card.width() - 20, FILENAME_BAR)
        painter.setPen(QColor(MUTED))
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        caption = photo["filename"]
        taken = photo.get("taken_at") or photo.get("mtime")
        if taken:
            caption += f" · {datetime.fromtimestamp(taken):%Y-%m-%d}"
        elided = painter.fontMetrics().elidedText(
            caption, Qt.ElideMiddle, name_rect.width()
        )
        painter.drawText(name_rect, Qt.AlignCenter, elided)

        selected = option.state & QStyle.State_Selected
        hovered = option.state & QStyle.State_MouseOver
        painter.setClipping(False)
        painter.setPen(
            QPen(QColor(ACCENT if selected or hovered else BORDER), 2 if selected else 1)
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(card).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.restore()


class GalleryView(QListView):
    photo_clicked = Signal(dict)

    def __init__(self, loader, parent=None):
        super().__init__(parent)
        self.setObjectName("gallery")
        self._model = PhotoModel(self)
        self.delegate = PhotoDelegate(loader, self)
        self.setModel(self._model)
        self.setItemDelegate(self.delegate)

        self.columns = DEFAULT_COLUMNS
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(30)
        # Keep the scrollbar permanent so its appearance never re-triggers layout.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)

        loader.thumb_ready.connect(lambda *_: self.viewport().update())
        self.clicked.connect(self._on_clicked)

    def set_columns(self, columns):
        self.columns = max(2, min(8, int(columns)))
        self._update_grid()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            photo = self.currentIndex().data(Qt.UserRole)
            if photo is not None:
                self.photo_clicked.emit(photo)
                return
        super().keyPressEvent(event)

    def _update_grid(self):
        """Fit self.columns columns into the viewport; cards scale with the window."""
        cell_w = max(GAP + 40, self.viewport().width() // self.columns)
        card_w = cell_w - GAP
        frame_h = round(card_w / THUMB_ASPECTS[self.delegate.aspect_key])
        cell_h = frame_h + FILENAME_BAR + GAP
        size = QSize(cell_w, cell_h)
        if size != self.delegate.cell_size:
            self.delegate.cell_size = size
            self.setGridSize(size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_grid()

    def set_photos(self, photos):
        self._model.set_photos(photos)

    def set_aspect(self, aspect_key):
        self.delegate.aspect_key = aspect_key
        self._update_grid()
        self.reset()  # re-measure the uniform item size

    def set_show_boxes(self, show):
        self.delegate.show_boxes = show
        self.viewport().update()

    def _on_clicked(self, index):
        photo = index.data(Qt.UserRole)
        if photo is not None:
            self.photo_clicked.emit(photo)
