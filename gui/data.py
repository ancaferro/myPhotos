"""Read/write queries used by the GUI (ported from the old HTTP API)."""

from database import get_db

# Thumbnails are fixed-aspect crops centered on the detected faces.
THUMB_ASPECTS = {"34": 3 / 4, "43": 4 / 3}
THUMB_MAX = {"34": (450, 600), "43": (600, 450)}
PORTRAIT_SIZE = 128


def compute_crop(
    width: int, height: int, faces: list[dict], aspect: float
) -> dict[str, int]:
    """Fixed-aspect crop window centered on the faces' bounding box (or the middle).

    Returned in original-image coordinates; the same window is used to build
    the thumbnail and to place face boxes on previews.
    """
    if width / height > aspect:
        crop_w, crop_h = round(height * aspect), height
    else:
        crop_w, crop_h = width, round(width / aspect)

    if faces:
        x1 = min(f["x"] for f in faces)
        y1 = min(f["y"] for f in faces)
        x2 = max(f["x"] + f["w"] for f in faces)
        y2 = max(f["y"] + f["h"] for f in faces)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    else:
        cx, cy = width / 2, height / 2

    x = min(max(round(cx - crop_w / 2), 0), width - crop_w)
    y = min(max(round(cy - crop_h / 2), 0), height - crop_h)
    return {"x": x, "y": y, "w": crop_w, "h": crop_h}


def list_photos(person_id: int | None = None, aspect_key: str = "34") -> list[dict]:
    db = get_db()
    if person_id is None:
        rows = db.execute("SELECT * FROM photos ORDER BY filename").fetchall()
    else:
        rows = db.execute(
            "SELECT DISTINCT p.* FROM photos p"
            " JOIN faces f ON f.photo_id = p.id"
            " WHERE f.person_id = ? ORDER BY p.filename",
            (person_id,),
        ).fetchall()

    face_rows = db.execute(
        "SELECT f.id, f.photo_id, f.person_id, f.x, f.y, f.w, f.h, pe.name AS person_name"
        " FROM faces f LEFT JOIN persons pe ON pe.id = f.person_id"
    ).fetchall()
    db.close()

    faces_by_photo = {}
    for f in face_rows:
        faces_by_photo.setdefault(f["photo_id"], []).append(
            {
                "id": f["id"],
                "person_id": f["person_id"],
                "person_name": f["person_name"],
                "x": f["x"], "y": f["y"], "w": f["w"], "h": f["h"],
            }
        )

    return [
        {
            "id": p["id"],
            "filename": p["filename"],
            "path": p["path"],
            "width": p["width"],
            "height": p["height"],
            "faces": faces_by_photo.get(p["id"], []),
            "crop": compute_crop(
                p["width"], p["height"], faces_by_photo.get(p["id"], []),
                THUMB_ASPECTS[aspect_key],
            ),
        }
        for p in rows
    ]


def list_persons() -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT pe.id, pe.name,"
        "       COUNT(DISTINCT f.photo_id) AS photo_count,"
        "       COUNT(f.id) AS face_count,"
        "       (SELECT id FROM faces WHERE person_id = pe.id"
        "        ORDER BY score DESC, w * h DESC LIMIT 1) AS portrait_face_id"
        " FROM persons pe LEFT JOIN faces f ON f.person_id = pe.id"
        " GROUP BY pe.id HAVING face_count > 0 ORDER BY photo_count DESC, pe.id"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def rename_person(person_id: int, name: str) -> None:
    db = get_db()
    db.execute("UPDATE persons SET name = ? WHERE id = ?", (name, person_id))
    db.commit()
    db.close()


def delete_person(person_id: int) -> None:
    """Delete a person together with its face boxes (e.g. false detections)."""
    db = get_db()
    db.execute("DELETE FROM faces WHERE person_id = ?", (person_id,))
    db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    db.commit()
    db.close()


def merge_person(source_id: int, target_id: int) -> None:
    """Move all faces of source_id into target_id and delete source_id."""
    db = get_db()
    db.execute("UPDATE faces SET person_id = ? WHERE person_id = ?", (target_id, source_id))
    db.execute("DELETE FROM persons WHERE id = ?", (source_id,))
    db.commit()
    db.close()


def face_portrait_source(face_id: int) -> dict | None:
    """Photo path and face rect for a person's avatar, or None if missing."""
    db = get_db()
    row = db.execute(
        "SELECT f.x, f.y, f.w, f.h, p.path FROM faces f"
        " JOIN photos p ON p.id = f.photo_id WHERE f.id = ?",
        (face_id,),
    ).fetchone()
    db.close()
    return dict(row) if row is not None else None
