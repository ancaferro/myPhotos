"""myPhotos — face cataloging web app (Flask + OpenCV + SQLite)."""

import io
import os

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageOps

from analyzer import Analyzer
from database import get_db, init_db
from paths import default_photos_dir, resource_dir

DEFAULT_FOLDER = default_photos_dir()
# Thumbnails are fixed-aspect crops centered on the detected faces.
THUMB_ASPECTS = {"34": 3 / 4, "43": 4 / 3}
THUMB_MAX = {"34": (450, 600), "43": (600, 450)}
PORTRAIT_SIZE = 128

app = Flask(__name__, static_folder=os.path.join(resource_dir(), "static"))
analyzer = Analyzer()
init_db()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    return jsonify({"default_folder": DEFAULT_FOLDER})


@app.post("/api/analyze")
def analyze():
    folder = (request.get_json(silent=True) or {}).get("folder", "").strip()
    if not folder:
        return jsonify({"error": "Folder is required"}), 400
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder}"}), 400
    if not analyzer.start(folder):
        return jsonify({"error": "Analysis is already running"}), 409
    return jsonify({"ok": True})


@app.get("/api/progress")
def progress():
    return jsonify(analyzer.get_progress())


def _aspect_key():
    key = request.args.get("aspect", "34")
    return key if key in THUMB_ASPECTS else "34"


def compute_crop(width, height, faces, aspect):
    """Fixed-aspect crop window centered on the faces' bounding box (or the middle).

    Returned in original-image coordinates; the same window is used by the
    thumbnail endpoint and by the frontend to place face boxes on previews.
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


@app.get("/api/photos")
def photos():
    person_id = request.args.get("person_id", type=int)
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

    return jsonify(
        [
            {
                "id": p["id"],
                "filename": p["filename"],
                "path": p["path"],
                "width": p["width"],
                "height": p["height"],
                "faces": faces_by_photo.get(p["id"], []),
                "crop": compute_crop(
                    p["width"], p["height"], faces_by_photo.get(p["id"], []),
                    THUMB_ASPECTS[_aspect_key()],
                ),
            }
            for p in rows
        ]
    )


@app.get("/api/persons")
def persons():
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
    return jsonify([dict(r) for r in rows])


@app.post("/api/persons/<int:person_id>/rename")
def rename_person(person_id):
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    db = get_db()
    cur = db.execute("UPDATE persons SET name = ? WHERE id = ?", (name, person_id))
    db.commit()
    db.close()
    if cur.rowcount == 0:
        abort(404)
    return jsonify({"ok": True, "name": name})


@app.delete("/api/persons/<int:person_id>")
def delete_person(person_id):
    """Delete a person together with its face boxes (e.g. false detections)."""
    db = get_db()
    exists = db.execute("SELECT 1 FROM persons WHERE id = ?", (person_id,)).fetchone()
    if exists is None:
        db.close()
        abort(404)
    db.execute("DELETE FROM faces WHERE person_id = ?", (person_id,))
    db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.post("/api/persons/<int:person_id>/merge")
def merge_person(person_id):
    """Move all faces of person_id into target_id and delete person_id."""
    target_id = (request.get_json(silent=True) or {}).get("target_id")
    if not isinstance(target_id, int) or target_id == person_id:
        return jsonify({"error": "Valid target_id is required"}), 400
    db = get_db()
    source = db.execute("SELECT 1 FROM persons WHERE id = ?", (person_id,)).fetchone()
    target = db.execute("SELECT 1 FROM persons WHERE id = ?", (target_id,)).fetchone()
    if source is None or target is None:
        db.close()
        abort(404)
    db.execute("UPDATE faces SET person_id = ? WHERE person_id = ?", (target_id, person_id))
    db.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


def _load_photo(photo_id):
    db = get_db()
    row = db.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    db.close()
    if row is None or not os.path.isfile(row["path"]):
        abort(404)
    return row


def _jpeg_response(image):
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=85)
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@app.get("/api/thumb/<int:photo_id>")
def thumb(photo_id):
    row = _load_photo(photo_id)
    db = get_db()
    faces = [
        dict(f)
        for f in db.execute(
            "SELECT x, y, w, h FROM faces WHERE photo_id = ?", (photo_id,)
        ).fetchall()
    ]
    db.close()
    key = _aspect_key()
    crop = compute_crop(row["width"], row["height"], faces, THUMB_ASPECTS[key])
    with Image.open(row["path"]) as img:
        img = ImageOps.exif_transpose(img)
        img = img.crop((crop["x"], crop["y"], crop["x"] + crop["w"], crop["y"] + crop["h"]))
        img.thumbnail(THUMB_MAX[key])
        return _jpeg_response(img)


@app.get("/api/image/<int:photo_id>")
def full_image(photo_id):
    row = _load_photo(photo_id)
    return send_file(row["path"])


@app.get("/api/face/<int:face_id>")
def face_portrait(face_id):
    db = get_db()
    row = db.execute(
        "SELECT f.x, f.y, f.w, f.h, p.path FROM faces f"
        " JOIN photos p ON p.id = f.photo_id WHERE f.id = ?",
        (face_id,),
    ).fetchone()
    db.close()
    if row is None or not os.path.isfile(row["path"]):
        abort(404)

    with Image.open(row["path"]) as img:
        img = ImageOps.exif_transpose(img)
        # Square crop around the face with a 30% margin.
        cx, cy = row["x"] + row["w"] / 2, row["y"] + row["h"] / 2
        side = max(row["w"], row["h"]) * 1.3
        box = (
            max(0, int(cx - side / 2)),
            max(0, int(cy - side / 2)),
            min(img.width, int(cx + side / 2)),
            min(img.height, int(cy + side / 2)),
        )
        crop = img.crop(box)
        crop.thumbnail((PORTRAIT_SIZE, PORTRAIT_SIZE))
        return _jpeg_response(crop)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
