"""Tests for analyzer helpers: file scan, clustering and recluster mapping."""

import numpy as np

import analyzer
from analyzer import (
    GREEDY_THRESHOLD,
    Analyzer,
    _average_linkage,
    _normalize,
    scan_image_files,
)


def _unit(dim, axis, noise_seed=None):
    vec = np.zeros(dim, dtype=np.float32)
    vec[axis] = 1.0
    if noise_seed is not None:
        rng = np.random.default_rng(noise_seed)
        vec = vec + rng.normal(0, 0.01, dim).astype(np.float32)
    return vec / np.linalg.norm(vec)


class TestScan:
    def test_recursive_sorted_and_filtered(self, tmp_path):
        (tmp_path / "sub").mkdir()
        for name in ["b.JPG", "a.png", "sub/c.webp", "notes.txt", "d.tiff"]:
            (tmp_path / name).write_bytes(b"x")
        files = scan_image_files(str(tmp_path))
        names = [f.replace(str(tmp_path) + "/", "") for f in files]
        assert names == sorted(["b.JPG", "a.png", "sub/c.webp", "d.tiff"])


class TestNormalize:
    def test_unit_norm(self):
        vec = _normalize(np.array([3.0, 4.0], dtype=np.float32))
        assert abs(np.linalg.norm(vec) - 1.0) < 1e-6

    def test_zero_vector_unchanged(self):
        vec = _normalize(np.zeros(4, dtype=np.float32))
        assert not np.any(vec)


class TestAverageLinkage:
    def test_two_tight_groups(self):
        embeddings = np.stack(
            [_unit(8, 0, s) for s in range(3)] + [_unit(8, 1, s) for s in range(3)]
        )
        clusters = _average_linkage(embeddings, threshold=0.3)
        assert sorted(sorted(c) for c in clusters) == [[0, 1, 2], [3, 4, 5]]

    def test_orthogonal_vectors_stay_separate(self):
        embeddings = np.stack([_unit(4, i) for i in range(4)])
        clusters = _average_linkage(embeddings, threshold=0.3)
        assert len(clusters) == 4


def _with_similarity(cos):
    """Unit vector whose dot product with the axis-0 unit vector equals cos."""
    vec = np.zeros(8, dtype=np.float32)
    vec[0] = cos
    vec[1] = np.sqrt(1.0 - cos * cos)
    return vec


class TestAssignPerson:
    def test_close_embedding_joins_existing_person(self, db):
        conn = db.get_db()
        a = Analyzer()
        persons = {}
        first = a._assign_person(conn, persons, _unit(8, 0))
        second = a._assign_person(conn, persons, _with_similarity(0.9))
        assert second == first
        assert len(persons[first]) == 2
        conn.close()

    def test_distant_embedding_creates_new_person(self, db):
        conn = db.get_db()
        a = Analyzer()
        persons = {}
        first = a._assign_person(conn, persons, _unit(8, 0))
        second = a._assign_person(conn, persons, _unit(8, 1))
        assert second != first
        assert set(persons) == {first, second}
        names = {r["name"] for r in conn.execute("SELECT name FROM persons")}
        assert names == {f"Persona {first}", f"Persona {second}"}
        conn.close()

    def test_similarity_threshold_boundary(self, db):
        conn = db.get_db()
        a = Analyzer()
        persons = {}
        first = a._assign_person(conn, persons, _unit(8, 0))
        joined = a._assign_person(
            conn, persons, _with_similarity(GREEDY_THRESHOLD + 0.02)
        )
        assert joined == first
        split = a._assign_person(
            conn, {first: [_unit(8, 0)]}, _with_similarity(GREEDY_THRESHOLD - 0.02)
        )
        assert split != first
        conn.close()

    def test_embeddings_per_person_are_capped(self, db, monkeypatch):
        monkeypatch.setattr(analyzer, "MAX_EMBEDDINGS_PER_PERSON", 3)
        conn = db.get_db()
        a = Analyzer()
        persons = {}
        first = a._assign_person(conn, persons, _unit(8, 0))
        for seed in range(1, 6):
            assert a._assign_person(conn, persons, _unit(8, 0, seed)) == first
        assert len(persons[first]) == 3  # capped, membership unchanged
        conn.close()


def _seed_faces(db, groups):
    """Insert one photo and faces: groups is a list of (axis, person_id)."""
    conn = db.get_db()
    photo_id = conn.execute(
        "INSERT INTO photos (path, filename, width, height, mtime)"
        " VALUES ('/x.jpg', 'x.jpg', 100, 100, 0)"
    ).lastrowid
    max_person = max(pid for _, pid in groups)
    for pid in range(1, max_person + 1):
        conn.execute("INSERT INTO persons (id, name) VALUES (?, ?)", (pid, f"P{pid}"))
    face_ids = []
    for i, (axis, person_id) in enumerate(groups):
        emb = _unit(8, axis, noise_seed=i)
        face_ids.append(
            conn.execute(
                "INSERT INTO faces (photo_id, person_id, x, y, w, h, score, embedding)"
                " VALUES (?, ?, 0, 0, 30, 30, 0.9, ?)",
                (photo_id, person_id, emb.tobytes()),
            ).lastrowid
        )
    conn.commit()
    return conn, face_ids


class TestRecluster:
    def test_manual_merge_of_two_clusters_is_preserved(self, db):
        # Two distinct embedding groups, all manually assigned to person 1.
        conn, face_ids = _seed_faces(db, [(0, 1), (0, 1), (1, 1), (1, 1)])
        Analyzer()._recluster(conn, confirmed_ids=set(face_ids))
        persons = conn.execute(
            "SELECT DISTINCT person_id FROM faces"
        ).fetchall()
        assert [r["person_id"] for r in persons] == [1]
        conn.close()

    def test_greedy_overmerge_is_split_for_fresh_faces(self, db):
        # Group A confirmed as person 1; group B greedily got person 1 this run.
        conn, face_ids = _seed_faces(db, [(0, 1), (0, 1), (1, 1), (1, 1)])
        Analyzer()._recluster(conn, confirmed_ids=set(face_ids[:2]))
        rows = conn.execute("SELECT id, person_id FROM faces ORDER BY id").fetchall()
        by_face = {r["id"]: r["person_id"] for r in rows}
        assert by_face[face_ids[0]] == by_face[face_ids[1]] == 1
        assert by_face[face_ids[2]] == by_face[face_ids[3]] != 1
        conn.close()

    def test_orphaned_persons_are_deleted(self, db):
        conn, face_ids = _seed_faces(db, [(0, 1), (0, 1), (0, 2)])
        # All three faces form one cluster; person 1 wins the vote 2:1 and
        # person 2 loses its only face.
        Analyzer()._recluster(conn, confirmed_ids=set(face_ids))
        names = [r["name"] for r in conn.execute("SELECT name FROM persons").fetchall()]
        assert names == ["P1"]
        conn.close()

    def test_small_and_large_sets_are_skipped(self, db, monkeypatch):
        conn, face_ids = _seed_faces(db, [(0, 1)])
        Analyzer()._recluster(conn, confirmed_ids=set())  # single face: no-op
        assert conn.execute("SELECT person_id FROM faces").fetchone()[0] == 1
        monkeypatch.setattr(analyzer, "MAX_RECLUSTER_FACES", 0)
        Analyzer()._recluster(conn, confirmed_ids=set())  # over the cap: no-op
        assert conn.execute("SELECT person_id FROM faces").fetchone()[0] == 1
        conn.close()
