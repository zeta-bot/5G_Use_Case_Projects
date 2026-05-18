"""
Classroom Attendance System — RetinaFace + ArcFace
====================================================
Phase 1: Register students (build face database)
Phase 2: Run attendance on classroom photo/webcam/video

Install:
    pip install retina-face deepface opencv-python pandas openpyxl
"""

import cv2
import numpy as np
import os
import json
import csv
import pickle
import argparse
from collections import deque, Counter
from datetime import datetime
from pathlib import Path

# ── Optional imports (graceful fallback) ──────────────────────────────────────
try:
    from retinaface import RetinaFace
    RETINA_OK = True
except ImportError:
    RETINA_OK = False
    print("[WARN] retinaface not installed → pip install retina-face")

try:
    from deepface import DeepFace
    DEEPFACE_OK = True
except ImportError:
    DEEPFACE_OK = False
    print("[WARN] deepface not installed   → pip install deepface")

# ── Configuration ──────────────────────────────────────────────────────────────
CFG = {
    "db_path":         "face_db.pkl",       # stored embeddings
    "attendance_dir":  "attendance",         # output CSV/Excel folder
    "threshold":       0.8,                 # cosine distance (lower = stricter)
    "detect_threshold": 0.90,               # RetinaFace confidence
    "model":           "ArcFace",           # DeepFace model for embeddings
    "detector_backend":"retinaface",
    "box_known":   (0, 200, 80),            # green
    "box_unknown": (30, 30, 220),           # red
    "font":        cv2.FONT_HERSHEY_SIMPLEX,
    "output_dir":  "output",
}

# ──────────────────────────────────────────────────────────────────────────────
# Temporal Smoothing
# ──────────────────────────────────────────────────────────────────────────────

class TemporalSmoother:
    """
    Smooths face identity predictions over a sliding window of frames.

    For each detected face, we match it to an existing track using IoU
    (intersection-over-union) of bounding boxes.  Each track stores the
    last `window` (name, distance) predictions.  The final identity is
    chosen by majority vote; the reported distance is the mean of the
    matching-name detections within the window.

    Usage:
        smoother = TemporalSmoother(window=5, iou_threshold=0.35)

        # call once per processed frame, passing raw process_frame results
        smoothed_results = smoother.update(raw_results)

        # smoothed_results has the same schema as raw_results but with
        # stabilised "name", "distance", and "present" fields.
    """

    def __init__(self, window: int = 5, iou_threshold: float = 0.35):
        self.window        = window
        self.iou_threshold = iou_threshold
        # track_id → {"bbox": [...], "history": deque([(name, dist), ...])}
        self._tracks: dict[int, dict] = {}
        self._next_id = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _iou(a: list, b: list) -> float:
        """Compute IoU between two [x1,y1,x2,y2] boxes."""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter + 1e-9)

    def _match_or_create(self, bbox: list) -> int:
        """
        Find the best matching track for *bbox* (by IoU).
        Creates a new track if no match exceeds iou_threshold.
        Returns the track id.
        """
        best_id, best_iou = -1, self.iou_threshold
        for tid, track in self._tracks.items():
            iou = self._iou(track["bbox"], bbox)
            if iou > best_iou:
                best_iou = iou
                best_id  = tid

        if best_id == -1:
            best_id = self._next_id
            self._next_id += 1
            self._tracks[best_id] = {
                "bbox":    bbox,
                "history": deque(maxlen=self.window),
            }
        else:
            self._tracks[best_id]["bbox"] = bbox   # update position

        return best_id

    def _prune_stale_tracks(self, active_ids: set):
        """Remove tracks that were not matched in this frame."""
        stale = [tid for tid in self._tracks if tid not in active_ids]
        for tid in stale:
            del self._tracks[tid]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, raw_results: list[dict]) -> list[dict]:
        """
        Consume one frame's raw detections and return temporally smoothed
        results with the same dict schema.

        Parameters
        ----------
        raw_results : list[dict]
            Output of process_frame() — each dict has keys:
            name, distance, present, confidence, bbox

        Returns
        -------
        list[dict]
            Same structure, but name / distance / present are stabilised
            across the last `window` frames.
        """
        smoothed    = []
        active_ids  = set()

        for r in raw_results:
            tid = self._match_or_create(r["bbox"])
            active_ids.add(tid)

            track = self._tracks[tid]
            track["history"].append((r["name"], r["distance"]))

            # ── Majority-vote identity ───────────────────────────────
            names   = [h[0] for h in track["history"]]
            vote    = Counter(names).most_common(1)[0][0]

            # ── Mean distance for the winning name ───────────────────
            matching_dists = [h[1] for h in track["history"] if h[0] == vote]
            avg_dist       = float(np.mean(matching_dists))

            smoothed.append({
                **r,                            # keep bbox, confidence, …
                "name":     vote,
                "distance": round(avg_dist, 4),
                "present":  vote != "Unknown",
            })

        self._prune_stale_tracks(active_ids)
        return smoothed


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────

def load_db() -> dict:
    """Load {name: [embedding, ...]} from pickle file."""
    if os.path.exists(CFG["db_path"]):
        with open(CFG["db_path"], "rb") as f:
            return pickle.load(f)
    return {}


def save_db(db: dict):
    with open(CFG["db_path"], "wb") as f:
        pickle.dump(db, f)
    print(f"[INFO] Database saved → {CFG['db_path']}  ({len(db)} students)")


# ──────────────────────────────────────────────────────────────────────────────
# Embedding helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_embedding(face_crop: np.ndarray) -> np.ndarray | None:
    """
    Run ArcFace embedding on a cropped face image.
    Returns a unit-normalised 512-d vector, or None on failure.
    """
    if not DEEPFACE_OK:
        raise RuntimeError("deepface not installed")
    try:
        result = DeepFace.represent(
            img_path=face_crop,
            model_name=CFG["model"],
            detector_backend="skip",   # face already cropped — skip detection
            enforce_detection=False,
        )
        vec = np.array(result[0]["embedding"], dtype=np.float32)
        return vec / (np.linalg.norm(vec) + 1e-9)
    except Exception as e:
        print(f"  [WARN] Embedding failed: {e}")
        return None


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b))


def identify(embedding: np.ndarray, db: dict) -> tuple[str, float]:
    """
    Compare embedding against every stored face.
    Returns (name, best_distance). name='Unknown' if above threshold.
    """
    best_name, best_dist = "Unknown", 1.0
    for name, emb_list in db.items():
        for stored_emb in emb_list:
            dist = cosine_distance(embedding, stored_emb)
            if dist < best_dist:
                best_dist = dist
                best_name = name
    if best_dist > CFG["threshold"]:
        return "Unknown", best_dist
    return best_name, best_dist


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — Register students
# ──────────────────────────────────────────────────────────────────────────────

def register_from_folder(photos_dir: str):
    """
    Register all students from a folder structure:
        photos/
            Alice/   photo1.jpg  photo2.jpg ...
            Bob/     photo1.jpg  ...
    Each sub-folder name becomes the student's name.
    """
    db = load_db()
    photos_path = Path(photos_dir)

    for student_dir in sorted(photos_path.iterdir()):
        if not student_dir.is_dir():
            continue
        name = student_dir.name
        embeddings = []
        image_files = list(student_dir.glob("*.jpg")) + \
                      list(student_dir.glob("*.jpeg")) + \
                      list(student_dir.glob("*.png"))

        print(f"\n[INFO] Registering: {name}  ({len(image_files)} photo(s))")

        for img_path in image_files:
            img = cv2.imread(str(img_path))
            if img is None:
                print(f"  [SKIP] Cannot read {img_path.name}")
                continue

            # Detect face in photo
            faces = RetinaFace.detect_faces(img, threshold=CFG["detect_threshold"])
            if not isinstance(faces, dict) or len(faces) == 0:
                print(f"  [SKIP] No face found in {img_path.name}")
                continue

            # Use the most confident face
            best = max(faces.values(), key=lambda f: f["score"])
            x1, y1, x2, y2 = best["facial_area"]
            crop = img[max(0,y1):y2, max(0,x1):x2]

            emb = get_embedding(crop)
            if emb is not None:
                embeddings.append(emb)
                print(f"  [OK]  {img_path.name}")

        if embeddings:
            db[name] = embeddings
            print(f"  Stored {len(embeddings)} embedding(s) for {name}")
        else:
            print(f"  [WARN] No valid embeddings for {name}, skipping")

    save_db(db)
    print(f"\n[DONE] {len(db)} students registered.")


def register_single(name: str, photo_path: str):
    """Register a single student from one photo."""
    db = load_db()
    img = cv2.imread(photo_path)
    if img is None:
        print(f"[ERROR] Cannot read: {photo_path}")
        return

    faces = RetinaFace.detect_faces(img, threshold=CFG["detect_threshold"])
    if not isinstance(faces, dict):
        print("[ERROR] No face detected in photo")
        return

    best = max(faces.values(), key=lambda f: f["score"])
    x1, y1, x2, y2 = best["facial_area"]
    crop = img[max(0,y1):y2, max(0,x1):x2]
    emb = get_embedding(crop)
    if emb is None:
        print("[ERROR] Could not generate embedding")
        return

    if name not in db:
        db[name] = []
    db[name].append(emb)
    save_db(db)
    print(f"[OK] Registered {name} (total embeddings: {len(db[name])})")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — Run attendance
# ──────────────────────────────────────────────────────────────────────────────

def _annotate_frame(frame: np.ndarray, db: dict, results: list[dict]) -> tuple[np.ndarray, list[dict]]:
    """
    Draw bounding boxes, labels, and HUD onto *frame* using pre-computed
    *results*.  Returns (annotated_frame, results) for chaining convenience.
    This is separated from detection so temporal-smoothed results can be
    rendered without re-running the expensive embedding pipeline.
    """
    h, w   = frame.shape[:2]
    output = frame.copy()

    for r in results:
        x1, y1, x2, y2 = r["bbox"]
        is_known  = r["present"]
        color     = CFG["box_known"] if is_known else CFG["box_unknown"]
        name      = r["name"]
        dist      = r["distance"]

        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)

        label = f"{name}  ({dist:.2f})"
        (tw, th), _ = cv2.getTextSize(label, CFG["font"], 0.55, 1)
        ly = y1 - 6 if y1 > 24 else y2 + 20
        cv2.rectangle(output, (x1, ly - th - 4), (x1 + tw + 6, ly + 2), color, -1)
        cv2.putText(output, label, (x1 + 3, ly - 2),
                    CFG["font"], 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    # HUD
    ts      = datetime.now().strftime("%H:%M:%S")
    present = sum(1 for r in results if r["present"])
    cv2.putText(output, f"Present: {present}/{len(db)}  {ts}",
                (10, h - 10), CFG["font"], 0.5, (200, 200, 200), 1, cv2.LINE_AA)

    return output, results


def process_frame(frame: np.ndarray, db: dict) -> tuple[np.ndarray, list[dict]]:
    """
    Detect + identify faces in one frame.
    Returns annotated frame and list of result dicts.

    Note: for video/webcam paths the annotation is re-done by _annotate_frame
    after temporal smoothing, so the drawn labels here are only used for the
    single-image mode.
    """
    results = []
    h, w = frame.shape[:2]

    faces = RetinaFace.detect_faces(frame, threshold=CFG["detect_threshold"])
    if not isinstance(faces, dict):
        return frame, results

    for face_data in faces.values():
        x1, y1, x2, y2 = face_data["facial_area"]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        emb = get_embedding(crop)
        if emb is None:
            continue

        name, dist  = identify(emb, db)
        is_known    = name != "Unknown"
        confidence  = face_data.get("score", 0)

        # Collect landmarks separately for annotation
        landmarks = face_data.get("landmarks", {})

        results.append({
            "name":       name,
            "distance":   round(dist, 4),
            "present":    is_known,
            "confidence": round(confidence, 3),
            "bbox":       [x1, y1, x2, y2],
            "landmarks":  landmarks,
        })

    # Draw landmarks (kept in process_frame; smoothing doesn't change landmark positions)
    output = frame.copy()
    for r in results:
        for pt in r.get("landmarks", {}).values():
            cv2.circle(output, (int(pt[0]), int(pt[1])), 3, (80, 220, 255), -1)

    # Annotate with raw (unsmoothed) identities — overwritten for video/webcam
    output, _ = _annotate_frame(output, db, results)

    return output, results


def save_attendance(records: list[dict], session_tag: str = ""):
    """Save attendance list to CSV."""
    os.makedirs(CFG["attendance_dir"], exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    tag      = f"_{session_tag}" if session_tag else ""
    csv_path = os.path.join(CFG["attendance_dir"], f"attendance{tag}_{date_str}.csv")

    # Summarise: one row per unique identified student
    seen = {}
    for r in records:
        if r["present"] and r["name"] not in seen:
            seen[r["name"]] = r

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "distance", "confidence", "time"])
        writer.writeheader()
        for name, r in sorted(seen.items()):
            writer.writerow({
                "name":       name,
                "distance":   r["distance"],
                "confidence": r["confidence"],
                "time":       datetime.now().strftime("%H:%M:%S"),
            })

    print(f"[INFO] Attendance saved → {csv_path}  ({len(seen)} present)")
    return csv_path


# ──────────────────────────────────────────────────────────────────────────────
# Run modes
# ──────────────────────────────────────────────────────────────────────────────

def run_image(path: str):
    db = load_db()
    if not db:
        print("[ERROR] No students registered. Run: python attendance.py register --dir photos/")
        return

    img = cv2.imread(path)
    if img is None:
        print(f"[ERROR] Cannot read image: {path}")
        return

    print(f"[INFO] Processing: {path}")
    annotated, results = process_frame(img, db)

    present = [r["name"] for r in results if r["present"]]
    print(f"\nPresent ({len(present)}):", ", ".join(present) or "none")
    absent  = [n for n in db if n not in present]
    print(f"Absent  ({len(absent)}):",  ", ".join(absent)  or "none")

    csv_path = save_attendance(results, "image")

    os.makedirs(CFG["output_dir"], exist_ok=True)
    out = os.path.join(CFG["output_dir"], "attendance_" + os.path.basename(path))
    cv2.imwrite(out, annotated)
    print(f"[INFO] Annotated image → {out}")

    print("[INFO] Open the annotated image from the output/ folder to view results.")


def run_webcam(camera_id: int = 0):
    db = load_db()
    if not db:
        print("[ERROR] No students registered.")
        return

    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera {camera_id}")
        return

    print("[INFO] Webcam running. Press Ctrl+C to stop and save attendance.")
    print("[INFO] Snapshots will be saved to output/ every ~5 seconds.")
    print("[INFO] Temporal smoothing: 5-frame majority vote enabled.")
    all_results  = []
    detect_every = 8
    frame_no     = 0
    last_frame   = None
    smoother     = TemporalSmoother(window=15)   # ← temporal smoother

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Camera read failed, retrying...")
                continue
            frame_no += 1

            if frame_no % detect_every == 0:
                _, raw_results        = process_frame(frame, db)
                new_results           = smoother.update(raw_results)   # smooth
                # Re-draw annotations with smoothed identities
                last_frame, _         = _annotate_frame(frame, db, new_results)
                all_results.extend(new_results)
                if new_results:
                    present = [r["name"] for r in new_results if r["present"]]
                    if present:
                        print(f"[LIVE] Detected: {', '.join(present)}")

            # Save snapshot every ~5 seconds (detect_every * 40 frames ≈ 5s at 25fps*8)
            if frame_no % (detect_every * 40) == 0 and last_frame is not None:
                os.makedirs(CFG["output_dir"], exist_ok=True)
                snap = os.path.join(CFG["output_dir"], f"webcam_snap_{frame_no}.jpg")
                cv2.imwrite(snap, last_frame)
                print(f"[INFO] Snapshot saved → {snap}")

            # Auto-save attendance every 300 frames (~2 min)
            if frame_no % 300 == 0 and all_results:
                save_attendance(all_results, f"webcam_auto")
                print(f"[INFO] Auto-saved attendance at frame {frame_no}")

    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user (Ctrl+C)")
    finally:
        cap.release()
        if all_results:
            save_attendance(all_results, "webcam_final")
        print("[INFO] Webcam released. Check output/ and attendance/ folders.")


def run_video(path: str):
    db = load_db()
    if not db:
        print("[ERROR] No students registered.")
        return

    cap = cv2.VideoCapture(path)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 25
    w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    os.makedirs(CFG["output_dir"], exist_ok=True)
    out_path = os.path.join(CFG["output_dir"], "attendance_" + os.path.basename(path))
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (w, h))

    detect_every = max(1, int(fps // 2))
    all_results  = []
    last_frame   = None
    frame_no     = 0
    smoother     = TemporalSmoother(window=15)   # ← temporal smoother

    print(f"[INFO] Processing video ({total} frames)...")
    print("[INFO] Temporal smoothing: 5-frame majority vote enabled.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_no += 1

        if frame_no % detect_every == 0:
            _, raw_results   = process_frame(frame, db)
            new_results      = smoother.update(raw_results)     # smooth
            # Re-draw with smoothed identities
            last_frame, _    = _annotate_frame(frame, db, new_results)
            all_results.extend(new_results)

        writer.write(last_frame if last_frame is not None else frame)

        if frame_no % 50 == 0:
            pct = 100 * frame_no / total if total else 0
            print(f"  {frame_no}/{total} ({pct:.0f}%)")

    cap.release()
    writer.release()
    save_attendance(all_results, "video")
    print(f"[INFO] Annotated video → {out_path}")


def list_students():
    db = load_db()
    if not db:
        print("No students registered yet.")
        return
    print(f"\nRegistered students ({len(db)}):")
    for name, embs in sorted(db.items()):
        print(f"  {name:30s}  {len(embs)} embedding(s)")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Classroom Attendance — RetinaFace + ArcFace"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # register sub-command
    reg = sub.add_parser("register", help="Add students to the face database")
    reg_src = reg.add_mutually_exclusive_group(required=True)
    reg_src.add_argument("--dir",   help="Folder with student sub-folders")
    reg_src.add_argument("--photo", help="Single photo path")
    reg.add_argument("--name", help="Student name (required with --photo)")

    # attendance sub-commands
    img_p = sub.add_parser("image",   help="Take attendance from an image")
    img_p.add_argument("--source", required=True, help="Image path")

    web_p = sub.add_parser("webcam",  help="Live webcam attendance")
    web_p.add_argument("--source", default="0", help="Camera ID")

    vid_p = sub.add_parser("video",   help="Attendance from a video file")
    vid_p.add_argument("--source", required=True, help="Video path")

    sub.add_parser("list", help="List registered students")

    args = parser.parse_args()

    if not RETINA_OK or not DEEPFACE_OK:
        print("\n[ERROR] Missing dependencies.")
        print("Install: pip install retina-face deepface opencv-python pandas\n")
        return

    if args.cmd == "register":
        if args.dir:
            register_from_folder(args.dir)
        elif args.photo:
            if not args.name:
                parser.error("--name is required when using --photo")
            register_single(args.name, args.photo)
    elif args.cmd == "image":
        run_image(args.source)
    elif args.cmd == "webcam":
        run_webcam(int(args.source))
    elif args.cmd == "video":
        run_video(args.source)
    elif args.cmd == "list":
        list_students()


if __name__ == "__main__":
    main()
