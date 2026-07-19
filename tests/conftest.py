"""Shared fixtures: offscreen Qt, a temp database and synthetic photos."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

import database  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Fresh SQLite database in a temp dir; database.DB_PATH is patched."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    return database


def _embedding(seed, dim=8):
    """Deterministic unit vector; nearby seeds in the same hundred are close."""
    base = np.zeros(dim, dtype=np.float32)
    base[seed // 100] = 1.0
    rng = np.random.default_rng(seed)
    vec = base + rng.normal(0, 0.01, dim).astype(np.float32)
    return vec / np.linalg.norm(vec)


@pytest.fixture()
def seeded(db, tmp_path):
    """Three photos (two persons: Alice on 1&2, Bob on 2&3) with real files.

    Returns a dict with photo/person ids for assertions.
    """
    conn = db.get_db()
    sizes = [(400, 300), (300, 400), (600, 600)]
    photo_ids = []
    for i, (w, h) in enumerate(sizes, start=1):
        path = tmp_path / f"img{i}.jpg"
        Image.new("RGB", (w, h), ((i * 60) % 255, 120, 160)).save(path)
        cur = conn.execute(
            "INSERT INTO photos (path, filename, width, height, mtime)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(path), path.name, w, h, os.path.getmtime(path)),
        )
        photo_ids.append(cur.lastrowid)

    alice = conn.execute("INSERT INTO persons (name) VALUES ('Alice')").lastrowid
    bob = conn.execute("INSERT INTO persons (name) VALUES ('Bob')").lastrowid

    faces = [
        (photo_ids[0], alice, 10, 10, 50, 60, 0.9, 0),
        (photo_ids[1], alice, 100, 120, 40, 40, 0.95, 1),
        (photo_ids[1], bob, 200, 220, 60, 50, 0.8, 100),
        (photo_ids[2], bob, 300, 300, 80, 80, 0.99, 101),
    ]
    face_ids = []
    for photo_id, person_id, x, y, w, h, score, emb_seed in faces:
        cur = conn.execute(
            "INSERT INTO faces (photo_id, person_id, x, y, w, h, score, embedding)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (photo_id, person_id, x, y, w, h, score, _embedding(emb_seed).tobytes()),
        )
        face_ids.append(cur.lastrowid)
    conn.commit()
    conn.close()

    return {
        "photo_ids": photo_ids,
        "alice": alice,
        "bob": bob,
        "face_ids": face_ids,
    }


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("myPhotosTest")
    app.setApplicationName("myPhotosTest")
    return app


@pytest.fixture()
def isolated_settings(qapp, tmp_path):
    """Redirect QSettings to a temp ini file and wipe it."""
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings().clear()
    return QSettings


def wait_idle(qapp, window, timeout=10.0):
    """Process events until the image loader has no pending work."""
    import time

    deadline = time.time() + timeout
    while not window.loader.is_idle() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    for _ in range(20):
        qapp.processEvents()


@pytest.fixture()
def window(qapp, seeded, isolated_settings):
    from gui.window import MainWindow

    win = MainWindow()
    win.resize(1280, 860)
    win.show()
    wait_idle(qapp, win)
    yield win
    win.lightbox.close()
    win.close()
    win.deleteLater()
    qapp.processEvents()
