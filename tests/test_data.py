"""Tests for gui.data: crop math and the read/write queries."""

import numpy as np

from gui import data


class TestComputeCrop:
    def test_wide_image_portrait_crop_spans_height(self):
        crop = data.compute_crop(400, 300, [], 3 / 4)
        assert crop["h"] == 300
        assert crop["w"] == round(300 * 3 / 4)
        assert abs(crop["x"] - (400 - crop["w"]) / 2) <= 1

    def test_tall_image_landscape_crop_spans_width(self):
        crop = data.compute_crop(300, 400, [], 4 / 3)
        assert crop["w"] == 300
        assert crop["h"] == round(300 / (4 / 3))

    def test_no_faces_centers_on_middle(self):
        crop = data.compute_crop(600, 600, [], 3 / 4)
        assert crop["x"] + crop["w"] / 2 == 300

    def test_crop_centers_on_face_bbox(self):
        faces = [{"x": 500, "y": 100, "w": 50, "h": 50}]
        crop = data.compute_crop(1000, 400, faces, 3 / 4)
        center = crop["x"] + crop["w"] / 2
        assert abs(center - 525) <= 1

    def test_crop_clamped_inside_image(self):
        faces = [{"x": 980, "y": 380, "w": 20, "h": 20}]
        crop = data.compute_crop(1000, 400, faces, 3 / 4)
        assert crop["x"] >= 0 and crop["y"] >= 0
        assert crop["x"] + crop["w"] <= 1000
        assert crop["y"] + crop["h"] <= 400

    def test_both_aspects_have_correct_ratio(self):
        for key, aspect in data.THUMB_ASPECTS.items():
            crop = data.compute_crop(1234, 987, [], aspect)
            assert abs(crop["w"] / crop["h"] - aspect) < 0.01, key


class TestQueries:
    def test_list_photos_returns_all_with_faces(self, seeded):
        photos = data.list_photos()
        assert [p["filename"] for p in photos] == ["img1.jpg", "img2.jpg", "img3.jpg"]
        by_name = {p["filename"]: p for p in photos}
        assert len(by_name["img1.jpg"]["faces"]) == 1
        assert len(by_name["img2.jpg"]["faces"]) == 2
        assert all("crop" in p for p in photos)

    def test_list_photos_filtered_by_person(self, seeded):
        alice_photos = data.list_photos(person_ids=[seeded["alice"]])
        assert [p["filename"] for p in alice_photos] == ["img1.jpg", "img2.jpg"]
        assert all(
            any(f["person_id"] == seeded["alice"] for f in p["faces"])
            for p in alice_photos
        )

    def test_multi_person_filter_is_and(self, seeded):
        both = data.list_photos(person_ids=[seeded["alice"], seeded["bob"]])
        assert [p["filename"] for p in both] == ["img2.jpg"]  # only shared photo

    def test_sort_by_capture_date(self, seeded):
        photos = data.list_photos(order="date")
        assert [p["filename"] for p in photos] == ["img2.jpg", "img3.jpg", "img1.jpg"]
        assert [p["taken_at"] for p in photos] == [1000.0, 2000.0, 3000.0]

    def test_list_persons_counts_and_order(self, seeded):
        persons = data.list_persons()
        assert {p["name"] for p in persons} == {"Alice", "Bob"}
        for p in persons:
            assert p["photo_count"] == 2
            assert p["face_count"] == 2
            assert p["portrait_face_id"] is not None

    def test_portrait_face_is_highest_score(self, seeded):
        persons = {p["name"]: p for p in data.list_persons()}
        # Bob's img3 face has score 0.99 vs 0.8.
        assert persons["Bob"]["portrait_face_id"] == seeded["face_ids"][3]

    def test_rename_person(self, seeded):
        data.rename_person(seeded["alice"], "Alicia")
        assert {p["name"] for p in data.list_persons()} == {"Alicia", "Bob"}

    def test_merge_moves_faces_and_deletes_source(self, seeded):
        data.merge_person(seeded["alice"], seeded["bob"])
        persons = data.list_persons()
        assert len(persons) == 1
        assert persons[0]["id"] == seeded["bob"]
        assert persons[0]["face_count"] == 4
        assert persons[0]["photo_count"] == 3

    def test_delete_person_keeps_photos(self, seeded):
        data.delete_person(seeded["bob"])
        assert {p["name"] for p in data.list_persons()} == {"Alice"}
        photos = data.list_photos()
        assert len(photos) == 3  # photos stay
        assert len([f for p in photos for f in p["faces"]]) == 2  # Bob's boxes gone

    def test_face_portrait_source(self, seeded):
        row = data.face_portrait_source(seeded["face_ids"][0])
        assert row["x"] == 10 and row["w"] == 50
        assert row["path"].endswith("img1.jpg")
        assert data.face_portrait_source(99999) is None


def _seed_faces_for_clear(db, tmp_path):
    """One photo with a large high-score face, one with a tiny low-score face."""
    conn = db.get_db()
    person = conn.execute("INSERT INTO persons (name) VALUES ('Alice')").lastrowid
    specs = [
        (1000, 800, 400, 300, 0.99),  # clearly visible
        (1000, 800, 30, 20, 0.7),     # tiny and low confidence
    ]
    photo_ids = []
    for i, (w, h, fw, fh, score) in enumerate(specs):
        path = tmp_path / f"pic{i}.jpg"
        from PIL import Image

        Image.new("RGB", (w, h), (0, 0, 0)).save(path)
        pid = conn.execute(
            "INSERT INTO photos (path, filename, width, height, mtime)"
            " VALUES (?, ?, ?, ?, 1)",
            (str(path), path.name, w, h),
        ).lastrowid
        photo_ids.append(pid)
        conn.execute(
            "INSERT INTO faces (photo_id, person_id, x, y, w, h, score, embedding)"
            " VALUES (?, ?, 0, 0, ?, ?, ?, ?)",
            (pid, person, fw, fh, score, np.zeros(8, dtype=np.float32).tobytes()),
        )
    conn.commit()
    conn.close()
    return person, photo_ids


class TestClearFacesFilter:
    def test_clear_faces_keeps_only_clearly_visible_photos(self, db, tmp_path):
        person, photo_ids = _seed_faces_for_clear(db, tmp_path)
        photos = data.list_photos(person_ids=[person], clear_faces=True)
        assert [p["filename"] for p in photos] == ["pic0.jpg"]

    def test_without_clear_faces_both_photos_match(self, db, tmp_path):
        person, photo_ids = _seed_faces_for_clear(db, tmp_path)
        photos = data.list_photos(person_ids=[person])
        assert [p["filename"] for p in photos] == ["pic0.jpg", "pic1.jpg"]

    def test_clear_faces_requires_a_person_filter(self, db, tmp_path):
        person, photo_ids = _seed_faces_for_clear(db, tmp_path)
        assert len(data.list_photos(clear_faces=True)) == 2  # no person: no-op

    def test_clear_faces_combines_with_other_filters(self, db, tmp_path):
        person, photo_ids = _seed_faces_for_clear(db, tmp_path)
        photos = data.list_photos(person_ids=[person], clear_faces=True, with_location=True)
        assert photos == []  # no photo has coordinates
