"""
Face Image Capture Script — RetinaFace Edition
Captures images from webcam, detects faces with RetinaFace,
crops to the detected face region, and saves the crops.

Requirements:
    pip install opencv-python retina-face tf-keras
"""

import cv2
import os
import time
import argparse
from datetime import datetime

import numpy as np

# Suppress TensorFlow/oneDNN noise
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"


def load_retinaface_model():
    """Load the RetinaFace model once and return it."""
    print("[INFO] Loading RetinaFace model (first run downloads weights ~1 MB)...")
    from retinaface import RetinaFace
    model = RetinaFace.build_model()
    print("[INFO] RetinaFace model ready.\n")
    return model


def detect_and_crop(frame: np.ndarray, model, threshold: float, padding: float):
    """
    Run RetinaFace on a BGR frame.

    Returns:
        list of (cropped_bgr_image, facial_area, score) tuples.
        Empty list if no face detected.
    """
    from retinaface import RetinaFace

    # RetinaFace accepts BGR numpy arrays directly (same as cv2 frames)
    detections = RetinaFace.detect_faces(frame, threshold=threshold, model=model)

    crops = []
    if not isinstance(detections, dict):
        return crops  # no faces found

    h, w = frame.shape[:2]
    for face_key, face_data in detections.items():
        x1, y1, x2, y2 = face_data["facial_area"]

        # Add padding around the tight face box
        pad_x = int((x2 - x1) * padding)
        pad_y = int((y2 - y1) * padding)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)

        crop = frame[y1:y2, x1:x2]
        if crop.size > 0:
            crops.append((crop, face_data["facial_area"], face_data["score"]))

    return crops


def capture_face_images(
    num_images: int = 150,
    delay: float = 0.2,
    output_dir: str = None,
    show_preview: bool = True,
    camera_index: int = 0,
    threshold: float = 0.9,
    padding: float = 0.25,
    save_size: tuple = None,
):
    """
    Capture cropped face images from the webcam using RetinaFace.

    Args:
        num_images:   Target number of face crops to save.
        delay:        Minimum seconds between saves (default 0.2 s).
        output_dir:   Folder for saved crops. Auto-named if None.
        show_preview: Show live webcam window with bounding-box overlay.
        camera_index: OpenCV camera index (0 = default webcam).
        threshold:    RetinaFace confidence threshold (0-1, default 0.9).
        padding:      Fractional padding around the detected face box (default 0.25).
        save_size:    Resize saved crop to (W, H), e.g. (224, 224). None = no resize.
    """
    # ── Output directory ──────────────────────────────────────────────────────
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"face_crops_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    print(f"[INFO] Saving face crops to: {os.path.abspath(output_dir)}")

    # ── Load RetinaFace model (done once) ─────────────────────────────────────
    model = load_retinaface_model()

    # ── Open webcam ───────────────────────────────────────────────────────────
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open camera at index {camera_index}. "
            "Try a different --camera value."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print(f"[INFO] Starting capture — target: {num_images} face crops")
    print("[INFO] Press 'q' to quit early.\n")

    captured = 0
    last_save_time = 0.0

    while captured < num_images:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)   # mirror view
        now = time.time()

        # Run RetinaFace detection + crop
        crops = detect_and_crop(frame, model, threshold, padding)
        face_found = len(crops) > 0

        # ── Live preview with bounding boxes ──────────────────────────────────
        if show_preview:
            preview = frame.copy()
            for _, (x1, y1, x2, y2), score in crops:
                color = (0, 255, 80)
                cv2.rectangle(preview, (x1, y1), (x2, y2), color, 2)
                label = f"RetinaFace {score:.2f}"
                cv2.putText(
                    preview, label, (x1, max(y1 - 8, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2,
                )

            status_color = (0, 255, 80) if face_found else (0, 100, 255)
            status = (
                f"Saved: {captured}/{num_images}  |  "
                f"Face: {'YES' if face_found else 'NO'}"
            )
            cv2.putText(
                preview, status, (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2,
            )
            cv2.putText(
                preview, "Press 'q' to quit",
                (10, preview.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1,
            )

            cv2.imshow("RetinaFace Capture — press Q to quit", preview)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("\n[INFO] Stopped by user.")
                break

        # ── Save crops once per delay interval ────────────────────────────────
        if face_found and (now - last_save_time) >= delay:
            for crop_img, _, score in crops:
                if captured >= num_images:
                    break
                if save_size is not None:
                    crop_img = cv2.resize(
                        crop_img, save_size, interpolation=cv2.INTER_LANCZOS4
                    )
                filename = os.path.join(output_dir, f"face_{captured:04d}.jpg")
                cv2.imwrite(filename, crop_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                captured += 1

            last_save_time = now

            # Terminal progress bar
            progress = int((captured / num_images) * 30)
            bar = "█" * progress + "░" * (30 - progress)
            print(f"\r  [{bar}] {captured}/{num_images}", end="", flush=True)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cap.release()
    if show_preview:
        cv2.destroyAllWindows()

    print(f"\n\n[DONE] Saved {captured} face crops.")
    print(f"[DONE] Output folder: {os.path.abspath(output_dir)}")
    return output_dir, captured


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Capture & crop face images from webcam using RetinaFace."
    )
    parser.add_argument(
        "-n", "--num-images", type=int, default=150,
        help="Number of face crops to save (default: 150)",
    )
    parser.add_argument(
        "-d", "--delay", type=float, default=0.2,
        help="Min seconds between saves (default: 0.2)",
    )
    parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help="Output directory (default: face_crops_<timestamp>)",
    )
    parser.add_argument(
        "--no-preview", action="store_true",
        help="Disable the live preview window",
    )
    parser.add_argument(
        "-c", "--camera", type=int, default=0,
        help="Camera device index (default: 0)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.9,
        help="RetinaFace confidence threshold 0-1 (default: 0.9)",
    )
    parser.add_argument(
        "--padding", type=float, default=0.25,
        help="Fractional padding around face crop, e.g. 0.25 = 25%% extra (default: 0.25)",
    )
    parser.add_argument(
        "--size", type=int, nargs=2, metavar=("W", "H"), default=None,
        help="Resize saved crops to WxH, e.g. --size 224 224",
    )
    args = parser.parse_args()

    capture_face_images(
        num_images=args.num_images,
        delay=args.delay,
        output_dir=args.output_dir,
        show_preview=not args.no_preview,
        camera_index=args.camera,
        threshold=args.threshold,
        padding=args.padding,
        save_size=tuple(args.size) if args.size else None,
    )
