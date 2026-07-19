"""Error-path tests: data failures surface as dialogs, bad files degrade."""

from PySide6.QtCore import QPointF

import gui.window


def _boom(*args, **kwargs):
    raise RuntimeError("boom")


class TestReportedErrors:
    def test_photo_load_failure_is_reported_not_raised(self, window, monkeypatch):
        reported = []
        monkeypatch.setattr(
            window, "_report_error", lambda title, exc: reported.append(title)
        )
        monkeypatch.setattr(gui.window.data, "list_photos", _boom)
        window.refresh_photos()
        assert reported == ["Loading photos"]

    def test_person_load_failure_is_reported_not_raised(self, window, monkeypatch):
        reported = []
        monkeypatch.setattr(
            window, "_report_error", lambda title, exc: reported.append(title)
        )
        monkeypatch.setattr(gui.window.data, "list_persons", _boom)
        window.refresh_persons()
        assert reported == ["Loading people"]

    def test_delete_failure_keeps_window_alive(self, window, monkeypatch, qapp):
        from PySide6.QtWidgets import QMessageBox

        reported = []
        monkeypatch.setattr(
            window, "_report_error", lambda title, exc: reported.append(title)
        )
        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
        )
        monkeypatch.setattr(gui.window.data, "delete_person", _boom)
        person = window.people.persons()[0]
        window._delete_person(person)
        assert reported == ["Delete person"]
        assert len(window.people.persons()) == 2  # nothing was deleted


class TestBadFiles:
    def test_lightbox_shows_message_for_unreadable_file(self, qapp, window):
        photo = dict(window.gallery._model.photos()[0])
        photo["path"] = "/nonexistent/gone.jpg"
        window.lightbox.show_photos([photo], 0)
        qapp.processEvents()
        assert window.lightbox._pixmap is None
        window.lightbox.grab()  # paints the "Could not load image" state
        window.lightbox.accept()

    def test_unreadable_thumbnail_source_does_not_crash_loader(self, qapp, window):
        from tests.conftest import wait_idle

        photo = dict(window.gallery._model.photos()[0])
        photo["id"] = 987654
        photo["path"] = "/nonexistent/gone.jpg"
        assert window.loader.thumbnail(photo, "34") is None
        wait_idle(qapp, window)
        assert (987654, "34") not in window.loader._thumbs  # nothing cached
        assert window.loader.is_idle()  # the failed job did not get stuck
