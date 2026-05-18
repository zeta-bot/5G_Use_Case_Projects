from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Tuple

import cv2

try:
    from keras.models import load_model
except Exception:  # pragma: no cover
    from tensorflow.keras.models import load_model  # type: ignore


def load_trained_model(model_path: Path):
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model file not found: {model_path}. Place cnn_model_keras2.h5 from the source repo/training output at this path."
        )
    return load_model(str(model_path))


def load_gesture_labels(db_path: Path) -> Dict[int, str]:
    if not db_path.exists():
        raise FileNotFoundError(f"Gesture DB not found: {db_path}")

    labels: Dict[int, str] = {}
    with sqlite3.connect(str(db_path)) as conn:
        for g_id, g_name in conn.execute("SELECT g_id, g_name FROM gesture ORDER BY g_id"):
            labels[int(g_id)] = str(g_name)
    if not labels:
        raise RuntimeError(f"No gesture labels found in: {db_path}")
    return labels


def get_image_size(gestures_dir: Path) -> Tuple[int, int]:
    if gestures_dir.exists():
        for class_dir in sorted([p for p in gestures_dir.iterdir() if p.is_dir()]):
            sample = class_dir / "100.jpg"
            if sample.exists():
                img = cv2.imread(str(sample), 0)
                if img is not None:
                    return img.shape

            jpgs = list(class_dir.glob("*.jpg"))
            if jpgs:
                img = cv2.imread(str(jpgs[0]), 0)
                if img is not None:
                    return img.shape

    # Fallback used by the original code path for inference when gesture images are absent.
    return 50, 50
