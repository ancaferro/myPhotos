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


class TestThumbCacheBudget:
    """The disk cache must stay bounded: keys change with mtime, aspect and
    crop, so superseded files pile up unless something evicts them."""

    @staticmethod
    def _write(cache_dir, name, size, last_use):
        path = cache_dir / name
        path.write_bytes(b"\0" * size)
        os.utime(path, (last_use, last_use))
        return path

    def test_cache_size_and_clear(self, qapp, tmp_path):
        from gui.thumbs import ImageLoader

        loader = ImageLoader()
        cache_dir = tmp_path / "thumbs_cache"
        self._write(cache_dir, "a.jpg", 1000, 1_600_000_000)
        self._write(cache_dir, "b.jpg", 2000, 1_600_000_000)

        assert loader.cache_size() == 3000
        assert loader.clear_cache() == 3000
        assert loader.cache_size() == 0
        assert list(cache_dir.glob("*.jpg")) == []

    def test_trim_evicts_least_recently_used_first(self, qapp, tmp_path, monkeypatch):
        import gui.thumbs

        monkeypatch.setattr(gui.thumbs, "MAX_CACHE_BYTES", 2500)
        loader = gui.thumbs.ImageLoader()
        cache_dir = tmp_path / "thumbs_cache"
        oldest = self._write(cache_dir, "oldest.jpg", 1000, 1_600_000_000)
        middle = self._write(cache_dir, "middle.jpg", 1000, 1_600_001_000)
        newest = self._write(cache_dir, "newest.jpg", 1000, 1_600_002_000)

        loader._note_write()  # the loader is primed to trim on its first write

        assert loader.cache_size() <= 2500
        assert not oldest.exists()
        assert middle.exists() and newest.exists()

    def test_a_cache_hit_refreshes_last_use(self, qapp, tmp_path, monkeypatch):
        """Re-reading an entry must protect it from the next eviction."""
        import gui.thumbs

        monkeypatch.setattr(gui.thumbs, "MAX_CACHE_BYTES", 1500)
        loader = gui.thumbs.ImageLoader()
        cache_dir = tmp_path / "thumbs_cache"
        old = self._write(cache_dir, "old.jpg", 1000, 1_600_000_000)
        new = self._write(cache_dir, "new.jpg", 1000, 1_600_002_000)

        loader._touch(old)  # old.jpg was just served from disk
        loader._note_write()

        assert old.exists(), "a just-used entry must not be the one evicted"
        assert not new.exists()

    def test_stale_entries_do_not_grow_without_bound(self, qapp, tmp_path, monkeypatch):
        """Simulate repeated re-indexing: each round supersedes every key.

        Trimming is batched, so the size settles at the budget plus at most one
        trim interval's worth of fresh writes — the point is that it settles at
        all instead of growing with every round.
        """
        import gui.thumbs

        monkeypatch.setattr(gui.thumbs, "MAX_CACHE_BYTES", 10_000)
        monkeypatch.setattr(gui.thumbs, "TRIM_EVERY_WRITES", 5)
        loader = gui.thumbs.ImageLoader()
        cache_dir = tmp_path / "thumbs_cache"
        entry_size, rounds, per_round = 1000, 10, 5

        sizes = []
        for round_no in range(rounds):
            for i in range(per_round):
                self._write(
                    cache_dir,
                    f"1-{round_no}-34-{i}.jpg",
                    entry_size,
                    1_600_000_000 + round_no * 100 + i,
                )
                loader._note_write()
            sizes.append(loader.cache_size())

        ceiling = 10_000 + per_round * entry_size
        assert max(sizes) <= ceiling, f"cache exceeded its budget: {sizes}"
        # Without eviction this would be rounds * per_round * entry_size.
        assert sizes[-1] < rounds * per_round * entry_size / 2
        assert sizes[-1] == sizes[len(sizes) // 2], "size must settle, not creep"


class TestSettingsCacheRow:
    def test_dialog_reports_and_clears_the_cache(self, qapp, tmp_path):
        from gui.settings import SettingsDialog, format_size

        state = {"size": 5 * 1024 * 1024}

        def clear():
            state["size"] = 0

        dialog = SettingsDialog(
            {
                "columns": 4,
                "aspect": "34",
                "sort": "name",
                "watch": False,
                "greedy_threshold": 0.32,
                "cluster_threshold": 0.28,
                "log_level": "WARNING",
            },
            cache=(lambda: state["size"], clear),
        )
        assert dialog.cache_size.text() == "5 MB"
        assert dialog.clear_cache_btn.isEnabled()

        dialog.clear_cache_btn.click()
        assert state["size"] == 0
        assert dialog.cache_size.text() == "0 KB"
        assert not dialog.clear_cache_btn.isEnabled()
        dialog.deleteLater()

    def test_format_size(self):
        from gui.settings import format_size

        assert format_size(0) == "0 KB"
        assert format_size(2048) == "2 KB"
        assert format_size(3 * 1024 * 1024) == "3 MB"
        assert format_size(2 * 1024**3) == "2.0 GB"


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
