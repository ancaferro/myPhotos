"""Recursive photo scanning, face detection (YuNet) and face clustering (SFace)."""

import logging
import os
import sqlite3
import threading
from collections.abc import Set
from datetime import datetime

import cv2
import numpy as np

from database import get_db
from paths import resource_dir

log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(resource_dir(), "models")
DETECTOR_MODEL = os.path.join(MODELS_DIR, "face_detection_yunet_2023mar.onnx")
RECOGNIZER_MODEL = os.path.join(MODELS_DIR, "face_recognition_sface_2021dec.onnx")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# Cosine similarity threshold for the live (greedy, mean-linkage) assignment
# used while a run is in progress.
GREEDY_THRESHOLD = 0.32
# Threshold for the final average-linkage re-clustering of all faces. Lower
# than pairwise verification thresholds because it applies to cluster means.
CLUSTER_THRESHOLD = 0.28
# Full re-clustering is O(n^2) memory; above this face count keep greedy results.
MAX_RECLUSTER_FACES = 4000
DETECTION_SCORE_THRESHOLD = 0.8
MAX_DETECTION_SIDE = 1280
MIN_FACE_SIZE = 24
# At most this many embeddings per person are kept in memory for matching.
MAX_EMBEDDINGS_PER_PERSON = 32


# EXIF tags: DateTimeOriginal lives in the Exif sub-IFD, DateTime in IFD0.
EXIF_SUB_IFD = 0x8769
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME = 306


def read_taken_at(path: str) -> float | None:
    """Capture timestamp from EXIF metadata, or None when unavailable."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            exif = img.getexif()
            value = exif.get_ifd(EXIF_SUB_IFD).get(TAG_DATETIME_ORIGINAL) or exif.get(
                TAG_DATETIME
            )
        if not value:
            return None
        return datetime.strptime(str(value).strip(), "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:  # noqa: BLE001 - EXIF is best-effort
        return None


def scan_image_files(folder: str) -> list[str]:
    """Return sorted list of image file paths under folder, recursively."""
    files = []
    for root, _dirs, names in os.walk(folder):
        for name in names:
            if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                files.append(os.path.join(root, name))
    files.sort()
    return files


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _average_linkage(embeddings: np.ndarray, threshold: float) -> list[list[int]]:
    """Agglomerative average-linkage clustering on cosine similarities.

    Uses Lance-Williams updates on a full similarity matrix: O(n^2) memory,
    fine for a few thousand faces. Returns a list of index lists.
    """
    n = len(embeddings)
    sim = embeddings @ embeddings.T
    np.fill_diagonal(sim, -2.0)
    sizes = np.ones(n)
    members = {i: [i] for i in range(n)}
    active = np.ones(n, dtype=bool)

    while True:
        idx = np.flatnonzero(active)
        if len(idx) < 2:
            break
        sub = sim[np.ix_(idx, idx)]
        flat = int(np.argmax(sub))
        i_, j_ = divmod(flat, len(idx))
        if sub[i_, j_] < threshold:
            break
        i, j = int(idx[i_]), int(idx[j_])

        merged_row = (sizes[i] * sim[i] + sizes[j] * sim[j]) / (sizes[i] + sizes[j])
        sim[i, :] = merged_row
        sim[:, i] = merged_row
        sim[i, i] = -2.0
        sim[j, :] = -2.0
        sim[:, j] = -2.0
        sizes[i] += sizes[j]
        members[i].extend(members.pop(j))
        active[j] = False

    return [members[i] for i in np.flatnonzero(active)]


class Analyzer:
    """Runs analysis in a background thread and exposes progress state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.progress: dict[str, object] = {
            "status": "idle",  # idle | running | done | error
            "total": 0,
            "done": 0,
            "current": "",
            "error": "",
        }

    def _set(self, **kwargs: object) -> None:
        with self._lock:
            self.progress.update(kwargs)

    def get_progress(self) -> dict[str, object]:
        with self._lock:
            return dict(self.progress)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, folder: str) -> bool:
        if self.is_running():
            return False
        self._set(status="running", total=0, done=0, current="", error="")
        self._thread = threading.Thread(target=self._run, args=(folder,), daemon=True)
        self._thread.start()
        return True

    # ---------------------------------------------------------------- core

    def _run(self, folder: str) -> None:
        try:
            detector = cv2.FaceDetectorYN.create(
                DETECTOR_MODEL, "", (320, 320), DETECTION_SCORE_THRESHOLD
            )
            recognizer = cv2.FaceRecognizerSF.create(RECOGNIZER_MODEL, "")

            files = scan_image_files(folder)
            self._set(total=len(files))

            db = get_db()
            persons = self._load_persons(db)
            # Faces that existed before this run carry assignments from the
            # previous run and any manual edits (rename/merge); they outrank
            # this run's greedy guesses when clusters are mapped to persons.
            confirmed_ids = {r["id"] for r in db.execute("SELECT id FROM faces").fetchall()}

            for i, path in enumerate(files):
                self._set(done=i, current=os.path.basename(path))
                try:
                    self._process_photo(db, detector, recognizer, persons, path)
                except Exception as exc:  # noqa: BLE001 - skip unreadable files
                    log.warning("skipping %s: %s", path, exc)

            self._set(current="Clustering faces…")
            self._recluster(db, confirmed_ids)
            db.close()
            self._set(status="done", done=len(files), current="")
        except Exception as exc:  # noqa: BLE001
            log.exception("analysis of %s failed", folder)
            self._set(status="error", error=str(exc))

    def _load_persons(self, db: sqlite3.Connection) -> dict[int, list[np.ndarray]]:
        """Load stored embeddings grouped by person for incremental clustering."""
        persons: dict[int, list[np.ndarray]] = {}
        rows = db.execute(
            "SELECT person_id, embedding FROM faces WHERE person_id IS NOT NULL"
        ).fetchall()
        for row in rows:
            vec = _normalize(np.frombuffer(row["embedding"], dtype=np.float32))
            persons.setdefault(row["person_id"], []).append(vec)
        for embeddings in persons.values():
            del embeddings[MAX_EMBEDDINGS_PER_PERSON:]
        return persons

    def _process_photo(
        self,
        db: sqlite3.Connection,
        detector: cv2.FaceDetectorYN,
        recognizer: cv2.FaceRecognizerSF,
        persons: dict[int, list[np.ndarray]],
        path: str,
    ) -> None:
        mtime = os.path.getmtime(path)
        existing = db.execute("SELECT id, mtime FROM photos WHERE path = ?", (path,)).fetchone()
        if existing is not None:
            if abs(existing["mtime"] - mtime) < 1e-6:
                return  # already analyzed and unchanged
            # File changed: drop old record, faces cascade away.
            db.execute("DELETE FROM photos WHERE id = ?", (existing["id"],))
            db.commit()

        image = cv2.imread(path)
        if image is None:
            image = self._read_with_pillow(path)
        if image is None:
            raise ValueError("unreadable image")

        height, width = image.shape[:2]

        # Detect on a downscaled copy for speed, map boxes back to full size.
        scale = 1.0
        detect_img = image
        if max(width, height) > MAX_DETECTION_SIDE:
            scale = MAX_DETECTION_SIDE / max(width, height)
            detect_img = cv2.resize(image, (round(width * scale), round(height * scale)))

        detector.setInputSize((detect_img.shape[1], detect_img.shape[0]))
        _, detections = detector.detect(detect_img)

        cur = db.execute(
            "INSERT INTO photos (path, filename, width, height, mtime, taken_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (path, os.path.basename(path), width, height, mtime, read_taken_at(path)),
        )
        photo_id = cur.lastrowid

        if detections is not None:
            for det in detections:
                feature = recognizer.feature(recognizer.alignCrop(detect_img, det))
                embedding = _normalize(feature.flatten().astype(np.float32))

                x, y, w, h = (det[:4] / scale).round().astype(int)
                x, y = max(x, 0), max(y, 0)
                w, h = min(w, width - x), min(h, height - y)
                if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
                    continue

                person_id = self._assign_person(db, persons, embedding)
                db.execute(
                    "INSERT INTO faces (photo_id, person_id, x, y, w, h, score, embedding)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (photo_id, person_id, int(x), int(y), int(w), int(h),
                     float(det[14]), embedding.tobytes()),
                )
        db.commit()

    def _assign_person(
        self,
        db: sqlite3.Connection,
        persons: dict[int, list[np.ndarray]],
        embedding: np.ndarray,
    ) -> int:
        """Greedy mean-linkage match against known persons (live preview only).

        The final grouping is decided by _recluster() at the end of the run.
        """
        best_id, best_sim = None, -1.0
        for person_id, embeddings in persons.items():
            sim = float(np.mean([np.dot(embedding, e) for e in embeddings]))
            if sim > best_sim:
                best_id, best_sim = person_id, sim

        if best_id is not None and best_sim >= GREEDY_THRESHOLD:
            if len(persons[best_id]) < MAX_EMBEDDINGS_PER_PERSON:
                persons[best_id].append(embedding)
            return best_id

        person_id = self._create_person(db)
        persons[person_id] = [embedding]
        return person_id

    @staticmethod
    def _create_person(db: sqlite3.Connection) -> int:
        cur = db.execute("INSERT INTO persons (name) VALUES ('')")
        person_id = cur.lastrowid
        db.execute("UPDATE persons SET name = ? WHERE id = ?", (f"Persona {person_id}", person_id))
        return person_id

    # ----------------------------------------------------------- clustering

    def _recluster(
        self, db: sqlite3.Connection, confirmed_ids: Set[int] = frozenset()
    ) -> None:
        """Re-cluster all faces with average-linkage and remap to existing persons.

        Mapping clusters back to persons uses two passes:
        - Confirmed faces (existed before this run, i.e. previous results plus
          manual renames/merges) vote first and MAY map several clusters onto
          one person — that is what keeps a user's manual merge intact.
        - Faces assigned by this run's greedy pass vote second, one-to-one
          only, so a greedy over-merge cannot pull two clusters together.
        """
        rows = db.execute("SELECT id, person_id, embedding FROM faces").fetchall()
        if len(rows) < 2 or len(rows) > MAX_RECLUSTER_FACES:
            return

        face_ids = [r["id"] for r in rows]
        old_person = [r["person_id"] for r in rows]
        embeddings = np.stack(
            [_normalize(np.frombuffer(r["embedding"], dtype=np.float32)) for r in rows]
        )
        clusters = _average_linkage(embeddings, CLUSTER_THRESHOLD)

        # Per-cluster overlap counts with previous persons, split by whether
        # the vote comes from a confirmed face or a fresh (greedy) one.
        confirmed_overlaps = []  # (count, cluster_index, person_id)
        fresh_overlaps = []
        for ci, members in enumerate(clusters):
            confirmed_counts, fresh_counts = {}, {}
            for m in members:
                pid = old_person[m]
                if pid is None:
                    continue
                bucket = confirmed_counts if face_ids[m] in confirmed_ids else fresh_counts
                bucket[pid] = bucket.get(pid, 0) + 1
            confirmed_overlaps.extend((n, ci, pid) for pid, n in confirmed_counts.items())
            fresh_overlaps.extend((n, ci, pid) for pid, n in fresh_counts.items())

        cluster_person = {}
        used_persons = set()
        for count, ci, pid in sorted(confirmed_overlaps, reverse=True):
            if ci in cluster_person:
                continue
            cluster_person[ci] = pid
            used_persons.add(pid)
        for count, ci, pid in sorted(fresh_overlaps, reverse=True):
            if ci in cluster_person or pid in used_persons:
                continue
            cluster_person[ci] = pid
            used_persons.add(pid)

        for ci, members in enumerate(clusters):
            pid = cluster_person.get(ci)
            if pid is None:
                pid = self._create_person(db)
            db.executemany(
                "UPDATE faces SET person_id = ? WHERE id = ?",
                [(pid, face_ids[m]) for m in members],
            )

        db.execute(
            "DELETE FROM persons WHERE id NOT IN (SELECT DISTINCT person_id FROM faces"
            " WHERE person_id IS NOT NULL)"
        )
        db.commit()

    @staticmethod
    def _read_with_pillow(path: str) -> np.ndarray | None:
        """Fallback reader for formats cv2.imread cannot open."""
        try:
            from PIL import Image

            with Image.open(path) as img:
                return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:  # noqa: BLE001
            return None
