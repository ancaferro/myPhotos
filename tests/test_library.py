"""Tests for the 1.1 library features: cache, sorting, multi-filter,
keyboard navigation, settings and folder watching."""

import os
import sqlite3
from datetime import datetime

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

import analyzer
import database
import gui.window
from tests.conftest import wait_idle


class TestThumbCache:
    def test_thumbnails_are_cached_on_disk_and_survive_the_original(
        self, qapp, window, tmp_path
    ):
        from gui.thumbs import ImageLoader

        cache_dir = tmp_path / "thumbs_cache"
        cached = list(cache_dir.glob("*.jpg"))
        assert cached, "visible thumbnails should be written to the disk cache"

        # A fresh loader must serve the thumbnail from the cache alone.
        photo = window.gallery._model.photos()[0]
        os.remove(photo["path"])
        import time

        loader = ImageLoader()
        assert loader.thumbnail(photo, window.aspect_key) is None  # scheduled
        deadline = time.time() + 10
        while not loader.is_idle() and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        assert loader.thumbnail(photo, window.aspect_key) is not None


class TestCaptureDate:
    def test_read_taken_at_from_exif(self, tmp_path):
        from PIL import Image

        path = tmp_path / "exif.jpg"
        exif = Image.Exif()
        exif[analyzer.TAG_DATETIME] = "2024:05:01 12:30:00"
        Image.new("RGB", (10, 10)).save(path, exif=exif)
        assert analyzer.read_taken_at(str(path)) == datetime(
            2024, 5, 1, 12, 30
        ).timestamp()

    def test_read_taken_at_missing_or_absent(self, tmp_path):
        from PIL import Image

        assert analyzer.read_taken_at(str(tmp_path / "missing.jpg")) is None
        path = tmp_path / "plain.jpg"
        Image.new("RGB", (10, 10)).save(path)
        assert analyzer.read_taken_at(str(path)) is None

    def test_old_database_gets_taken_at_column(self, tmp_path, monkeypatch):
        monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "old.db"))
        conn = sqlite3.connect(database.DB_PATH)
        conn.execute(
            "CREATE TABLE photos (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,"
            " filename TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,"
            " mtime REAL NOT NULL, analyzed_at TEXT)"
        )
        conn.commit()
        conn.close()
        database.init_db()
        columns = [
            row[1]
            for row in database.get_db().execute("PRAGMA table_info(photos)")
        ]
        assert "taken_at" in columns

    def test_sort_toggle_persists_and_reorders(self, qapp, window):
        assert window.sort_order == "name"
        window._toggle_sort()
        wait_idle(qapp, window)
        assert window.sort_order == "date"
        assert window.settings.value("sort") == "date"
        photos = window.gallery._model.photos()
        assert photos[0]["filename"] == "img2.jpg"  # earliest capture date


class TestMultiPersonFilter:
    def test_two_people_filter_with_and(self, qapp, window):
        alice, bob = window.people.persons()[:2]
        window._on_person_clicked(alice["id"])
        window._on_person_clicked(bob["id"])
        wait_idle(qapp, window)
        photos = window.gallery._model.photos()
        assert [p["filename"] for p in photos] == ["img2.jpg"]
        assert alice["name"] in window.filter_label.text()
        assert bob["name"] in window.filter_label.text()
        window._on_person_clicked(alice["id"])  # deselect one
        assert window.active_person_ids == {bob["id"]}


class TestKeyboard:
    def test_enter_opens_the_current_photo(self, qapp, window):
        index = window.gallery._model.index(1, 0)
        window.gallery.setCurrentIndex(index)
        window.gallery.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        )
        qapp.processEvents()
        assert window.lightbox.isVisible()
        assert window.lightbox._index == 1
        window.lightbox.accept()

    def test_escape_clears_the_person_filter(self, qapp, window):
        person = window.people.persons()[0]
        window._on_person_clicked(person["id"])
        assert window.active_person_ids
        window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not window.active_person_ids
        assert len(window.gallery._model.photos()) == 3


class TestSettings:
    def test_apply_settings_changes_grid_sort_and_thresholds(
        self, qapp, window, monkeypatch
    ):
        monkeypatch.setattr(analyzer, "GREEDY_THRESHOLD", 0.32)
        monkeypatch.setattr(analyzer, "CLUSTER_THRESHOLD", 0.28)
        window.apply_settings(
            {
                "columns": 5,
                "aspect": "34",
                "sort": "date",
                "watch": False,
                "greedy_threshold": 0.4,
                "cluster_threshold": 0.3,
                "log_level": "DEBUG",
            }
        )
        qapp.processEvents()
        view = window.gallery
        assert view.viewport().width() // view.gridSize().width() == 5
        assert window.sort_order == "date"
        assert analyzer.GREEDY_THRESHOLD == 0.4
        assert analyzer.CLUSTER_THRESHOLD == 0.3
        assert window.settings.value("columns") == 5
        import logging

        assert logging.getLogger().level == logging.DEBUG
        logging.getLogger().setLevel(logging.WARNING)

    def test_settings_dialog_round_trip(self, qapp):
        from gui.settings import SettingsDialog

        values = {
            "columns": 4,
            "aspect": "34",
            "sort": "name",
            "watch": True,
            "greedy_threshold": 0.32,
            "cluster_threshold": 0.28,
            "log_level": "INFO",
        }
        dialog = SettingsDialog(values)
        assert dialog.values() == values
        dialog.deleteLater()


class TestFolderWatching:
    def test_watch_covers_subdirectories(self, window, tmp_path):
        (tmp_path / "sub" / "deep").mkdir(parents=True)
        window.watch_enabled = True
        window._setup_watch(str(tmp_path))
        watched = set(window.watcher.directories())
        assert str(tmp_path) in watched
        assert str(tmp_path / "sub") in watched
        assert str(tmp_path / "sub" / "deep") in watched

    def test_disabled_watching_watches_nothing(self, window, tmp_path):
        window.watch_enabled = False
        window._setup_watch(str(tmp_path))
        assert window.watcher.directories() == []

    def test_change_triggers_debounced_rescan(self, window, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            window.analyzer, "start", lambda folder: calls.append(folder) or True
        )
        window.watch_enabled = True
        window.watched_folder = str(tmp_path)
        window._on_dir_changed(str(tmp_path))
        assert window.rescan_timer.isActive()
        window.rescan_timer.stop()
        window._auto_rescan()
        assert calls == [str(tmp_path)]
        window.poll_timer.stop()
        window._set_analyzing(False)
