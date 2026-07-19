"""Offscreen GUI tests: window state, responsive grid, lightbox interactions."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

from tests.conftest import wait_idle


def wheel(widget, pos, steps):
    widget.wheelEvent(
        QWheelEvent(
            pos, pos, QPoint(0, 0), QPoint(0, steps * 120),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
        )
    )


def press(widget, pos):
    widget.mousePressEvent(
        QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton,
                    Qt.LeftButton, Qt.NoModifier)
    )


def move(widget, pos):
    widget.mouseMoveEvent(
        QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton,
                    Qt.LeftButton, Qt.NoModifier)
    )


def release(widget, pos):
    widget.mouseReleaseEvent(
        QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton,
                    Qt.NoButton, Qt.NoModifier)
    )


def click(widget, pos):
    press(widget, pos)
    release(widget, pos)


class TestWindow:
    def test_gallery_and_people_populated(self, window):
        assert window.windowTitle() == "myPhotos"
        assert len(window.gallery._model.photos()) == 3
        assert len(window.people.persons()) == 2
        assert window.stack.currentIndex() == 0  # gallery, not empty state
        assert not window.filter_banner.isVisible()

    def test_person_filter_toggles(self, qapp, window):
        alice = window.people.persons()[0]
        window._on_person_clicked(alice["id"])
        wait_idle(qapp, window)
        assert len(window.gallery._model.photos()) == 2
        assert window.filter_banner.isVisible()
        assert alice["name"] in window.filter_label.text()
        window._on_person_clicked(alice["id"])  # same person: filter off
        assert len(window.gallery._model.photos()) == 3
        assert not window.filter_banner.isVisible()

    def test_people_rebuild_does_not_duplicate_rows(self, qapp, window):
        persons = window.people.persons()
        window.people.rebuild(persons, persons[0]["id"])
        window.people.rebuild(persons, None)
        qapp.processEvents()
        assert len(window.people._rows) == len(persons)

    def test_aspect_toggle_persists_between_windows(self, qapp, window, seeded):
        from gui.window import MainWindow

        assert window.aspect_key == "34"  # vertical by default
        window._toggle_aspect()
        assert window.aspect_key == "43"
        second = MainWindow()
        try:
            assert second.aspect_key == "43"
        finally:
            second.close()
            second.deleteLater()
            qapp.processEvents()

    def test_boxes_toggle_updates_delegate(self, window):
        assert window.gallery.delegate.show_boxes is True
        window._toggle_boxes()
        assert window.show_boxes is False
        assert window.gallery.delegate.show_boxes is False

    def test_empty_database_shows_empty_state(self, qapp, db, isolated_settings):
        from gui.window import MainWindow

        win = MainWindow()
        win.show()
        try:
            assert win.stack.currentIndex() == 1
            assert win.people.empty.isVisible() or not win.people.persons()
        finally:
            win.close()
            win.deleteLater()
            qapp.processEvents()


class TestGrid:
    @pytest.mark.parametrize("width", [1000, 1280, 1680])
    def test_always_four_columns(self, qapp, window, width):
        window.resize(width, 860)
        qapp.processEvents()
        view = window.gallery
        cell = view.gridSize().width()
        viewport = view.viewport().width()
        assert viewport // cell == 4
        assert viewport - 4 * cell < cell  # leftover smaller than a column


class TestLightbox:
    @pytest.fixture()
    def lightbox(self, qapp, window):
        window._open_lightbox(window.gallery._model.photos()[1])
        qapp.processEvents()
        return window.lightbox

    def test_opens_on_requested_photo(self, lightbox):
        assert lightbox.isVisible()
        assert lightbox._index == 1
        assert lightbox._pixmap is not None

    def test_wheel_zooms_around_cursor_and_back(self, lightbox):
        target = QPointF(lightbox.width() * 0.6, lightbox.height() * 0.4)
        wheel(lightbox, target, 4)
        assert abs(lightbox._zoom - 1.15 ** 4) < 1e-6
        wheel(lightbox, target, -10)
        assert lightbox._zoom == 1.0
        assert lightbox._pan == QPointF(0, 0)  # pan clamps to center at fit

    def test_drag_pans_when_overflowing(self, lightbox):
        center = QPointF(lightbox.width() / 2, lightbox.height() / 2)
        wheel(lightbox, center, 12)  # far beyond the window size
        size = lightbox._fit_size() * lightbox._zoom
        assert size.x() > lightbox.width() and size.y() > lightbox.height()
        pan_before = QPointF(lightbox._pan)
        press(lightbox, center)
        move(lightbox, center + QPointF(-80, -40))
        release(lightbox, center + QPointF(-80, -40))
        moved = lightbox._pan - pan_before
        assert abs(moved.x() + 80) < 2 and abs(moved.y() + 40) < 2
        assert lightbox.isVisible()  # a drag never closes the overlay

    def test_side_zones_navigate(self, lightbox):
        click(lightbox, QPointF(30, lightbox.height() / 2))
        assert lightbox._index == 0
        click(lightbox, QPointF(lightbox.width() - 30, lightbox.height() / 2))
        assert lightbox._index == 1

    def test_arrow_keys_navigate_without_wrap(self, lightbox):
        lightbox.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert lightbox._index == 2
        lightbox.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert lightbox._index == 2  # last photo: no wrap
        lightbox._load(0)
        lightbox.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier))
        assert lightbox._index == 0

    def test_close_button_top_right(self, qapp, lightbox):
        assert lightbox._close_btn.x() == lightbox.width() - 36 - 16
        assert lightbox._close_btn.y() == 16
        lightbox._close_btn.click()
        qapp.processEvents()
        assert not lightbox.isVisible()

    def test_background_click_closes(self, qapp, lightbox):
        corner = QPointF(lightbox.width() * 0.2, 20)
        assert lightbox._zone_at(corner) is None
        assert not lightbox._draw_rect().contains(corner)
        click(lightbox, corner)
        qapp.processEvents()
        assert not lightbox.isVisible()

    def test_navigation_resets_zoom(self, lightbox):
        wheel(lightbox, QPointF(lightbox.width() / 2, lightbox.height() / 2), 5)
        assert lightbox._zoom > 1
        lightbox._load(2)
        assert lightbox._zoom == 1.0
