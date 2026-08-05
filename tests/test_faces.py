"""Manual face management: assign, split, delete, and pinning across runs."""

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QInputDialog, QMessageBox

from analyzer import Analyzer
from gui import data
from tests.conftest import wait_idle


def _faces_of(photo_filename, photos):
    return next(p for p in photos if p["filename"] == photo_filename)["faces"]


class TestFaceEdits:
    def test_assign_moves_face_and_pins_it(self, db, seeded):
        face_id = seeded["face_ids"][0]  # img1, Alice
        data.assign_face(face_id, seeded["bob"])
        conn = db.get_db()
        row = conn.execute(
            "SELECT person_id, pinned FROM faces WHERE id = ?", (face_id,)
        ).fetchone()
        conn.close()
        assert row["person_id"] == seeded["bob"]
        assert row["pinned"] == 1

    def test_assigning_the_last_face_removes_the_empty_person(self, seeded):
        # Alice has two faces; move both to Bob.
        for face_id in seeded["face_ids"][:2]:
            data.assign_face(face_id, seeded["bob"])
        assert [p["name"] for p in data.list_persons()] == ["Bob"]
        assert data.list_persons()[0]["face_count"] == 4

    def test_split_creates_a_new_person(self, seeded):
        new_id = data.split_face_to_new_person(seeded["face_ids"][1], "Carol")
        persons = {p["name"]: p for p in data.list_persons()}
        assert set(persons) == {"Alice", "Bob", "Carol"}
        assert persons["Carol"]["id"] == new_id
        assert persons["Carol"]["face_count"] == 1
        assert persons["Alice"]["face_count"] == 1

    def test_delete_face_keeps_the_photo(self, seeded):
        data.delete_face(seeded["face_ids"][0])
        photos = data.list_photos()
        assert len(photos) == 3
        assert _faces_of("img1.jpg", photos) == []

    def test_deleting_every_face_of_a_person_removes_it(self, seeded):
        for face_id in seeded["face_ids"][:2]:  # both of Alice's faces
            data.delete_face(face_id)
        assert [p["name"] for p in data.list_persons()] == ["Bob"]


class TestPinnedSurvivesReclustering:
    def _seed_two_clusters(self, db):
        """Four faces in two well-separated embedding groups, persons 1 and 2."""
        conn = db.get_db()
        photo_id = conn.execute(
            "INSERT INTO photos (path, filename, width, height, mtime)"
            " VALUES ('/x.jpg', 'x.jpg', 100, 100, 0)"
        ).lastrowid
        for pid, name in ((1, "P1"), (2, "P2")):
            conn.execute("INSERT INTO persons (id, name) VALUES (?, ?)", (pid, name))
        face_ids = []
        for axis, person_id in ((0, 1), (0, 1), (1, 2), (1, 2)):
            vec = np.zeros(8, dtype=np.float32)
            vec[axis] = 1.0
            face_ids.append(
                conn.execute(
                    "INSERT INTO faces (photo_id, person_id, x, y, w, h, score, embedding)"
                    " VALUES (?, ?, 0, 0, 30, 30, 0.9, ?)",
                    (photo_id, person_id, vec.tobytes()),
                ).lastrowid
            )
        conn.commit()
        return conn, face_ids

    def test_pinned_face_keeps_its_person(self, db):
        conn, face_ids = self._seed_two_clusters(db)
        # The user insists this face of cluster B belongs to person 1.
        conn.execute(
            "UPDATE faces SET person_id = 1, pinned = 1 WHERE id = ?", (face_ids[2],)
        )
        conn.commit()

        Analyzer()._recluster(conn, confirmed_ids=set(face_ids))

        assignments = {
            r["id"]: r["person_id"]
            for r in conn.execute("SELECT id, person_id FROM faces")
        }
        assert assignments[face_ids[2]] == 1  # pinned, untouched by clustering
        assert assignments[face_ids[3]] != 1  # its cluster mate stays separate
        conn.close()

    def test_unpinned_faces_still_follow_the_clustering(self, db):
        conn, face_ids = self._seed_two_clusters(db)
        conn.execute("UPDATE faces SET person_id = 1 WHERE id = ?", (face_ids[2],))
        conn.commit()

        Analyzer()._recluster(conn, confirmed_ids=set())

        assignments = {
            r["id"]: r["person_id"]
            for r in conn.execute("SELECT id, person_id FROM faces")
        }
        # Without a pin the stray face is pulled back to its own cluster.
        assert assignments[face_ids[2]] == assignments[face_ids[3]]
        conn.close()


class TestFaceMenuInGui:
    def test_face_hit_testing_in_the_viewer(self, qapp, window):
        photos = window.gallery._model.photos()
        window._open_lightbox(photos[0])
        qapp.processEvents()
        lightbox = window.lightbox
        face = photos[0]["faces"][0]

        dst = lightbox._draw_rect()
        sx = dst.width() / photos[0]["width"]
        sy = dst.height() / photos[0]["height"]
        inside = QPointF(
            dst.x() + (face["x"] + face["w"] / 2) * sx,
            dst.y() + (face["y"] + face["h"] / 2) * sy,
        )
        assert lightbox.face_at(inside)["id"] == face["id"]
        assert lightbox.face_at(QPointF(dst.x() + 2, dst.y() + 2)) is None
        lightbox.accept()

    def test_menu_lists_the_other_people(self, qapp, window):
        photos = window.gallery._model.photos()
        face = photos[0]["faces"][0]  # Alice
        menu = window.build_face_menu(face)
        texts = [a.text() for a in menu.actions()]
        assert texts[0] == "Face: Alice"
        assert "Move to Bob" in texts
        assert "Move to Alice" not in texts  # already hers
        assert "Move to a new person…" in texts
        assert "Delete this face box" in texts
        menu.deleteLater()

    def test_moving_a_face_updates_the_sidebar_and_viewer(self, qapp, window):
        photos = window.gallery._model.photos()
        window._open_lightbox(photos[0])
        qapp.processEvents()
        face = photos[0]["faces"][0]
        bob = next(p for p in window.people.persons() if p["name"] == "Bob")

        window._assign_face(face, bob)
        wait_idle(qapp, window)

        persons = {p["name"]: p for p in window.people.persons()}
        assert persons["Bob"]["face_count"] == 3
        assert persons["Alice"]["face_count"] == 1
        updated = window.gallery._model.photos()
        assert _faces_of("img1.jpg", updated)[0]["person_name"] == "Bob"
        window.lightbox.accept()

    def test_deleting_a_face_asks_first(self, qapp, window, monkeypatch):
        face = window.gallery._model.photos()[0]["faces"][0]
        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No)
        )
        window._delete_face(face)
        assert _faces_of("img1.jpg", window.gallery._model.photos())

        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
        )
        window._delete_face(face)
        wait_idle(qapp, window)
        assert _faces_of("img1.jpg", window.gallery._model.photos()) == []

    def test_split_asks_for_a_name(self, qapp, window, monkeypatch):
        face = window.gallery._model.photos()[1]["faces"][0]
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False))
        )
        window._split_face(face)
        assert len(window.people.persons()) == 2  # cancelled

        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Carol", True))
        )
        window._split_face(face)
        wait_idle(qapp, window)
        assert "Carol" in [p["name"] for p in window.people.persons()]

    def test_viewer_closes_when_the_edit_empties_the_filter(self, qapp, window):
        alice = next(p for p in window.people.persons() if p["name"] == "Alice")
        window._on_person_clicked(alice["id"])
        wait_idle(qapp, window)
        photos = window.gallery._model.photos()
        window._open_lightbox(photos[0])  # img1, Alice's only solo photo
        qapp.processEvents()
        assert window.lightbox.isVisible()

        bob = next(p for p in window.people.persons() if p["name"] == "Bob")
        window._assign_face(photos[0]["faces"][0], bob)
        wait_idle(qapp, window)
        assert not window.lightbox.isVisible()
