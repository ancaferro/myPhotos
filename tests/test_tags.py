"""Tests for tags and EXIF location: storage, filtering and the GUI wiring."""

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from PySide6.QtWidgets import QInputDialog, QMessageBox

import analyzer
import gui.window
from gui import data
from tests.conftest import wait_idle


def _write_gps(path, lat_ref, lat, lon_ref, lon):
    exif = Image.Exif()
    exif[analyzer.GPS_IFD] = {
        analyzer.GPS_LAT_REF: lat_ref,
        analyzer.GPS_LAT: tuple(IFDRational(v) for v in lat),
        analyzer.GPS_LON_REF: lon_ref,
        analyzer.GPS_LON: tuple(IFDRational(v) for v in lon),
    }
    Image.new("RGB", (10, 10)).save(path, exif=exif)


class TestTagStorage:
    def test_create_is_idempotent_and_case_insensitive(self, db):
        first = data.create_tag("Vacation")
        assert data.create_tag("vacation") == first
        assert [t["name"] for t in data.list_tags()] == ["Vacation"]

    def test_attach_detach_and_counts(self, seeded):
        tag = data.create_tag("Trip")
        data.set_photo_tag(seeded["photo_ids"][:2], tag, True)
        assert data.list_tags()[0]["photo_count"] == 2
        data.set_photo_tag([seeded["photo_ids"][0]], tag, False)
        assert data.list_tags()[0]["photo_count"] == 1

    def test_attach_twice_does_not_duplicate(self, seeded):
        tag = data.create_tag("Trip")
        data.set_photo_tag([seeded["photo_ids"][0]], tag, True)
        data.set_photo_tag([seeded["photo_ids"][0]], tag, True)
        assert data.list_tags()[0]["photo_count"] == 1

    def test_rename_and_delete_keep_photos(self, seeded):
        tag = data.create_tag("Trip")
        data.set_photo_tag(seeded["photo_ids"], tag, True)
        data.rename_tag(tag, "Holiday")
        assert data.list_tags()[0]["name"] == "Holiday"
        data.delete_tag(tag)
        assert data.list_tags() == []
        assert len(data.list_photos()) == 3
        assert all(p["tags"] == [] for p in data.list_photos())

    def test_tags_are_reported_per_photo(self, seeded):
        tag = data.create_tag("Trip")
        data.set_photo_tag([seeded["photo_ids"][1]], tag, True)
        photos = {p["filename"]: p for p in data.list_photos()}
        assert [t["name"] for t in photos["img2.jpg"]["tags"]] == ["Trip"]
        assert photos["img1.jpg"]["tags"] == []


class TestFilters:
    def test_filter_by_tag(self, seeded):
        tag = data.create_tag("Trip")
        data.set_photo_tag(seeded["photo_ids"][:2], tag, True)
        photos = data.list_photos(tag_ids=[tag])
        assert [p["filename"] for p in photos] == ["img1.jpg", "img2.jpg"]

    def test_two_tags_combine_with_and(self, seeded):
        trip = data.create_tag("Trip")
        best = data.create_tag("Best")
        data.set_photo_tag(seeded["photo_ids"][:2], trip, True)
        data.set_photo_tag(seeded["photo_ids"][1:], best, True)
        photos = data.list_photos(tag_ids=[trip, best])
        assert [p["filename"] for p in photos] == ["img2.jpg"]

    def test_tag_and_person_combine(self, seeded):
        trip = data.create_tag("Trip")
        data.set_photo_tag([seeded["photo_ids"][0]], trip, True)
        # Alice is on img1 and img2; the tag narrows it to img1.
        photos = data.list_photos(person_ids=[seeded["alice"]], tag_ids=[trip])
        assert [p["filename"] for p in photos] == ["img1.jpg"]
        # Bob is not on img1, so the same tag yields nothing for him.
        assert data.list_photos(person_ids=[seeded["bob"]], tag_ids=[trip]) == []

    def test_location_filter(self, seeded):
        photos = data.list_photos(with_location=True)
        assert [p["filename"] for p in photos] == ["img3.jpg"]
        assert photos[0]["lat"] == pytest.approx(41.3874)
        assert photos[0]["lon"] == pytest.approx(2.1686)

    def test_location_filter_combines_with_person(self, seeded):
        # Bob is on img2 and img3; only img3 has coordinates.
        photos = data.list_photos(person_ids=[seeded["bob"]], with_location=True)
        assert [p["filename"] for p in photos] == ["img3.jpg"]


class TestGpsParsing:
    def test_northeast_coordinates(self, tmp_path):
        path = tmp_path / "bcn.jpg"
        _write_gps(path, "N", (41, 23, 14.7), "E", (2, 10, 7.2))
        lat, lon = analyzer.read_gps(str(path))
        assert lat == pytest.approx(41.3874, abs=1e-3)
        assert lon == pytest.approx(2.1686, abs=1e-3)

    def test_south_west_is_negative(self, tmp_path):
        path = tmp_path / "scl.jpg"
        _write_gps(path, "S", (33, 52, 0), "W", (70, 40, 0))
        lat, lon = analyzer.read_gps(str(path))
        assert lat == pytest.approx(-33.8667, abs=1e-3)
        assert lon == pytest.approx(-70.6667, abs=1e-3)

    def test_missing_or_unreadable_returns_none(self, tmp_path):
        plain = tmp_path / "plain.jpg"
        Image.new("RGB", (10, 10)).save(plain)
        assert analyzer.read_gps(str(plain)) is None
        assert analyzer.read_gps(str(tmp_path / "gone.jpg")) is None


class TestUpsertPhoto:
    def test_reanalysis_keeps_tags_and_replaces_faces(self, db, seeded, tmp_path):
        photo_id = seeded["photo_ids"][0]
        tag = data.create_tag("Trip")
        data.set_photo_tag([photo_id], tag, True)
        path = str(tmp_path / "img1.jpg")

        conn = db.get_db()
        same_id = analyzer.upsert_photo(conn, path, 400, 300, 999.0)
        conn.commit()
        assert same_id == photo_id  # the row survives, so the tag does too
        assert conn.execute(
            "SELECT COUNT(*) FROM photo_tags WHERE photo_id = ?", (photo_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM faces WHERE photo_id = ?", (photo_id,)
        ).fetchone()[0] == 0  # faces are re-detected by the caller
        assert conn.execute(
            "SELECT mtime FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()[0] == 999.0
        conn.close()

    def test_new_file_stores_capture_date_and_gps(self, db, tmp_path):
        path = tmp_path / "new.jpg"
        _write_gps(path, "N", (10, 0, 0), "E", (20, 0, 0))
        conn = db.get_db()
        photo_id = analyzer.upsert_photo(conn, str(path), 10, 10, 1.0)
        conn.commit()
        row = conn.execute(
            "SELECT lat, lon FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
        assert row["lat"] == pytest.approx(10.0)
        assert row["lon"] == pytest.approx(20.0)
        conn.close()


class TestTagsInGui:
    def test_tag_filter_and_banner(self, qapp, window):
        tag = data.create_tag("Trip")
        data.set_photo_tag([window.gallery._model.photos()[0]["id"]], tag, True)
        window.refresh_all()
        wait_idle(qapp, window)
        assert [t["name"] for t in window.tags.tags()] == ["Trip"]

        window._on_tag_clicked(tag)
        wait_idle(qapp, window)
        assert [p["filename"] for p in window.gallery._model.photos()] == ["img1.jpg"]
        assert "Trip" in window.filter_label.text()
        window._on_tag_clicked(tag)  # toggle off
        assert len(window.gallery._model.photos()) == 3

    def test_tagging_a_selection(self, qapp, window):
        tag = data.create_tag("Trip")
        window.refresh_all()
        photos = window.gallery._model.photos()[:2]
        window.toggle_tag_on(photos, tag, True)
        wait_idle(qapp, window)
        assert window.tags.tags()[0]["photo_count"] == 2
        window.toggle_tag_on(photos[:1], tag, False)
        assert window.tags.tags()[0]["photo_count"] == 1

    def test_new_tag_dialog_attaches_to_photos(self, qapp, window, monkeypatch):
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Beach", True))
        )
        window._new_tag(window.gallery._model.photos()[:1])
        wait_idle(qapp, window)
        assert window.tags.tags() == [
            {"id": window.tags.tags()[0]["id"], "name": "Beach", "photo_count": 1}
        ]

    def test_delete_tag_asks_and_clears_filter(self, qapp, window, monkeypatch):
        tag_id = data.create_tag("Trip")
        data.set_photo_tag([window.gallery._model.photos()[0]["id"]], tag_id, True)
        window.refresh_all()
        window._on_tag_clicked(tag_id)
        assert window.active_tag_ids == {tag_id}

        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
        )
        window._delete_tag(window.tags.tags()[0])
        wait_idle(qapp, window)
        assert window.tags.tags() == []
        assert window.active_tag_ids == set()
        assert len(window.gallery._model.photos()) == 3

    def test_location_toggle_filters_and_clears(self, qapp, window):
        window._toggle_location_filter()
        wait_idle(qapp, window)
        assert window.location_only is True
        assert [p["filename"] for p in window.gallery._model.photos()] == ["img3.jpg"]
        assert "with location" in window.filter_label.text()
        window._clear_filter()
        assert window.location_only is False
        assert len(window.gallery._model.photos()) == 3

    def test_escape_clears_every_filter(self, qapp, window):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        tag = data.create_tag("Trip")
        data.set_photo_tag([window.gallery._model.photos()[0]["id"]], tag, True)
        window.refresh_all()
        window._on_person_clicked(window.people.persons()[0]["id"])
        window._on_tag_clicked(tag)
        window._toggle_location_filter()
        assert window._has_filter()
        window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not window._has_filter()
        assert not window.filter_banner.isVisible()

    def test_context_menu_reflects_tags_of_the_selection(self, qapp, window):
        tag = data.create_tag("Trip")
        photos = window.gallery._model.photos()
        data.set_photo_tag([photos[0]["id"]], tag, True)
        window.refresh_all()
        wait_idle(qapp, window)
        photos = window.gallery._model.photos()

        menu = window.build_photo_menu(photos[0], [photos[0]])
        entries = [(a.text(), a.isCheckable(), a.isChecked()) for a in menu.actions()]
        assert "img1.jpg" in entries[0][0]
        assert ("Trip", True, True) in entries
        assert "New tag…" in [text for text, _, _ in entries]
        assert "Copy file path" in [text for text, _, _ in entries]
        menu.deleteLater()

        # The tag is only checked when every selected photo carries it.
        menu = window.build_photo_menu(photos[0], photos[:2])
        entries = [(a.text(), a.isChecked()) for a in menu.actions()]
        assert "2 photos" in entries[0][0]
        assert ("Trip", False) in entries
        menu.deleteLater()

    def test_context_menu_offers_location_actions_only_with_coordinates(
        self, qapp, window
    ):
        photos = {p["filename"]: p for p in window.gallery._model.photos()}
        with_gps = window.build_photo_menu(photos["img3.jpg"], [photos["img3.jpg"]])
        texts = [a.text() for a in with_gps.actions()]
        assert any("Copy coordinates" in t for t in texts)
        assert "Open location in OpenStreetMap" in texts
        with_gps.deleteLater()

        without = window.build_photo_menu(photos["img1.jpg"], [photos["img1.jpg"]])
        texts = [a.text() for a in without.actions()]
        assert not any("coordinates" in t for t in texts)
        without.deleteLater()
