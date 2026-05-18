from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import cv2

# Keep MediaPipe on CPU for compatibility across macOS environments.
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
import mediapipe as mp
import numpy as np


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build landmark CSV from labeled image folders")
    parser.add_argument("--input-dir", type=Path, required=True, help="Root containing class subfolders")
    parser.add_argument("--out", type=Path, default=Path("data/gestures.csv"))
    parser.add_argument("--min-detection-confidence", type=float, default=0.45)
    parser.add_argument("--max-images", type=int, default=0, help="0 means all")
    return parser.parse_args()


def normalize_landmarks(landmarks_xyz: np.ndarray) -> np.ndarray:
    wrist = landmarks_xyz[0]
    centered = landmarks_xyz - wrist
    scale = np.linalg.norm(centered, axis=1).max()
    scale = max(scale, 1e-6)
    normalized = centered / scale
    return normalized.reshape(-1).astype(np.float32)


def collect_image_paths(root: Path) -> List[Path]:
    # Path.rglob does not reliably traverse symlinked directories on some platforms.
    # We use os.walk(followlinks=True) so callers can point at a curated folder of symlinks.
    files: List[Path] = []
    for dirpath, _, filenames in os.walk(root, followlinks=True):
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                files.append(p)
    return sorted(files)


def infer_label(path: Path) -> str:
    # Expected structures include:
    # root/<label>/<file>
    # root/<split>/<label>/<file>
    parent = path.parent.name.strip()
    if parent.lower() in {"train", "test", "val", "valid", "validation"} and path.parent.parent:
        parent = path.parent.parent.name.strip()
    return parent.upper().replace(" ", "_")


def main() -> None:
    args = parse_args()
    if not args.input_dir.exists():
        raise FileNotFoundError(f"Input dir not found: {args.input_dir}")

    image_paths = collect_image_paths(args.input_dir)
    if not image_paths:
        raise RuntimeError(f"No images found under: {args.input_dir}")

    if args.max_images > 0:
        image_paths = image_paths[: args.max_images]

    args.out.parent.mkdir(parents=True, exist_ok=True)

    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=True,
        max_num_hands=1,
        model_complexity=0,
        min_detection_confidence=args.min_detection_confidence,
        min_tracking_confidence=0.5,
    )

    label_counts: Dict[str, int] = defaultdict(int)
    skipped = 0
    written = 0

    header = [f"f{i}" for i in range(63)] + ["label"]
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        total = len(image_paths)
        for idx, img_path in enumerate(image_paths, start=1):
            img = cv2.imread(str(img_path))
            if img is None:
                skipped += 1
                continue

            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = hands.process(img_rgb)

            if not results.multi_hand_landmarks:
                skipped += 1
                continue

            lm = results.multi_hand_landmarks[0]
            xyz = np.array([[p.x, p.y, p.z] for p in lm.landmark], dtype=np.float32)
            features = normalize_landmarks(xyz)
            label = infer_label(img_path)

            writer.writerow(features.tolist() + [label])
            written += 1
            label_counts[label] += 1

            if idx % 1000 == 0:
                print(f"Processed {idx}/{total} | written={written} | skipped={skipped}", flush=True)

    hands.close()

    print("\nDone.")
    print(f"Input images: {len(image_paths)}")
    print(f"Written rows: {written}")
    print(f"Skipped: {skipped}")
    print(f"Output CSV: {args.out}")

    sorted_counts = sorted(label_counts.items(), key=lambda kv: kv[0])
    print(f"Detected classes: {len(sorted_counts)}")
    for k, v in sorted_counts[:40]:
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
