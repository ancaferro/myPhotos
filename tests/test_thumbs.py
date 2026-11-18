"""Tests for the thumbnail disk-cache eviction (issue #27)."""

import os

from gui.thumbs import _evict_cache


def _write(path, size, mtime):
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))


def test_eviction_removes_oldest_until_under_budget(tmp_path):
    _write(tmp_path / "a.jpg", 100, 1000.0)
    _write(tmp_path / "b.jpg", 100, 2000.0)
    _write(tmp_path / "c.jpg", 100, 3000.0)
    _evict_cache(str(tmp_path), 250)
    # 300 bytes total, budget 250: drop the oldest (a) -> 200 bytes remain.
    assert sorted(os.listdir(tmp_path)) == ["b.jpg", "c.jpg"]


def test_eviction_keeps_cache_when_under_budget(tmp_path):
    _write(tmp_path / "a.jpg", 100, 1000.0)
    _write(tmp_path / "b.jpg", 100, 2000.0)
    _evict_cache(str(tmp_path), 500)
    assert sorted(os.listdir(tmp_path)) == ["a.jpg", "b.jpg"]


def test_eviction_ignores_subdirs_and_missing_dir(tmp_path):
    (tmp_path / "sub").mkdir()
    _evict_cache(str(tmp_path), 1)  # subdir is not a file, so nothing to evict
    assert sorted(os.listdir(tmp_path)) == ["sub"]
    _evict_cache(str(tmp_path / "missing"), 1)  # no such dir: no-op, no raise
