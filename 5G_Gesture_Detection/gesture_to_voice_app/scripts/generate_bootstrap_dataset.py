from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Tuple

import numpy as np


STATE_TO_LABEL: Dict[Tuple[int, int, int, int, int], str] = {
    (0, 0, 0, 0, 0): "SPEAK",
    (1, 1, 1, 1, 1): "HELLO",
    (0, 1, 0, 0, 0): "YES",
    (0, 1, 1, 0, 0): "NO",
    (0, 0, 1, 1, 1): "THANKS",
    (0, 1, 0, 0, 1): "SPACE",
    (1, 0, 0, 0, 1): "DELETE",
    (1, 1, 0, 0, 0): "CLEAR",
    (0, 0, 1, 0, 0): "PLEASE",
    (0, 0, 0, 1, 0): "SORRY",
    (0, 0, 0, 0, 1): "HELP",
    (1, 0, 0, 0, 0): "I",
    (0, 1, 0, 1, 0): "YOU",
    (0, 0, 1, 0, 1): "WE",
    (0, 0, 0, 1, 1): "GO",
    (1, 0, 1, 0, 0): "STOP",
    (1, 0, 0, 1, 0): "WATER",
    (1, 0, 1, 1, 0): "FOOD",
    (1, 1, 1, 0, 0): "LOVE",
    (0, 1, 1, 1, 0): "WANT",
    (0, 1, 1, 0, 1): "NEED",
    (0, 1, 1, 1, 1): "I_NEED_WATER",
    (1, 1, 1, 1, 0): "I_NEED_FOOD",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic landmark CSV for bootstrap MLP training")
    parser.add_argument("--out", type=Path, default=Path("data/gestures.csv"))
    parser.add_argument("--samples-per-class", type=int, default=600)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def normalize_landmarks(landmarks_xyz: np.ndarray) -> np.ndarray:
    wrist = landmarks_xyz[0]
    centered = landmarks_xyz - wrist
    scale = np.linalg.norm(centered, axis=1).max()
    scale = max(scale, 1e-6)
    normalized = centered / scale
    return normalized.reshape(-1).astype(np.float32)


def make_finger(mcp_x: float, is_open: bool, rng: np.random.Generator) -> np.ndarray:
    z_jitter = float(rng.normal(0.0, 0.01))
    if is_open:
        mcp = np.array([mcp_x, -0.10 + rng.normal(0, 0.02), z_jitter])
        pip = np.array([mcp_x + rng.normal(0, 0.01), -0.45 + rng.normal(0, 0.03), z_jitter])
        dip = np.array([mcp_x + rng.normal(0, 0.01), -0.75 + rng.normal(0, 0.03), z_jitter])
        tip = np.array([mcp_x + rng.normal(0, 0.01), -1.00 + rng.normal(0, 0.03), z_jitter])
    else:
        mcp = np.array([mcp_x, -0.10 + rng.normal(0, 0.02), z_jitter])
        pip = np.array([mcp_x + rng.normal(0, 0.01), 0.12 + rng.normal(0, 0.03), z_jitter])
        dip = np.array([mcp_x + rng.normal(0, 0.01), 0.20 + rng.normal(0, 0.03), z_jitter])
        tip = np.array([mcp_x + rng.normal(0, 0.01), 0.30 + rng.normal(0, 0.03), z_jitter])
    return np.vstack([mcp, pip, dip, tip])


def make_thumb(is_open: bool, rng: np.random.Generator) -> np.ndarray:
    z_jitter = float(rng.normal(0.0, 0.01))
    if is_open:
        cmc = np.array([-0.18 + rng.normal(0, 0.02), 0.02 + rng.normal(0, 0.02), z_jitter])
        mcp = np.array([-0.30 + rng.normal(0, 0.02), -0.06 + rng.normal(0, 0.02), z_jitter])
        ip = np.array([-0.40 + rng.normal(0, 0.02), -0.10 + rng.normal(0, 0.02), z_jitter])
        tip = np.array([-0.62 + rng.normal(0, 0.02), -0.22 + rng.normal(0, 0.02), z_jitter])
    else:
        cmc = np.array([-0.14 + rng.normal(0, 0.02), 0.03 + rng.normal(0, 0.02), z_jitter])
        mcp = np.array([-0.18 + rng.normal(0, 0.02), 0.05 + rng.normal(0, 0.02), z_jitter])
        ip = np.array([-0.20 + rng.normal(0, 0.02), 0.07 + rng.normal(0, 0.02), z_jitter])
        tip = np.array([-0.15 + rng.normal(0, 0.02), 0.10 + rng.normal(0, 0.02), z_jitter])
    return np.vstack([cmc, mcp, ip, tip])


def make_hand(state: Tuple[int, int, int, int, int], rng: np.random.Generator) -> np.ndarray:
    thumb_open, index_open, middle_open, ring_open, pinky_open = state

    wrist = np.array([[0.0 + rng.normal(0, 0.015), 0.0 + rng.normal(0, 0.015), rng.normal(0, 0.01)]])
    thumb = make_thumb(bool(thumb_open), rng)
    index = make_finger(-0.20, bool(index_open), rng)
    middle = make_finger(0.00, bool(middle_open), rng)
    ring = make_finger(0.20, bool(ring_open), rng)
    pinky = make_finger(0.40, bool(pinky_open), rng)

    hand = np.vstack([wrist, thumb, index, middle, ring, pinky])

    # Random in-plane rotation + translation + scale to emulate camera variation.
    theta = float(rng.uniform(-0.35, 0.35))
    c, s = np.cos(theta), np.sin(theta)
    rot = np.array([[c, -s], [s, c]], dtype=np.float32)
    scale = float(rng.uniform(0.8, 1.3))
    trans = np.array([rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2)], dtype=np.float32)

    hand_xy = hand[:, :2] @ rot.T
    hand_xy = (hand_xy * scale) + trans
    hand[:, :2] = hand_xy

    return hand


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    header = [f"f{i}" for i in range(63)] + ["label"]
    rows_written = 0

    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for state, label in STATE_TO_LABEL.items():
            for _ in range(args.samples_per_class):
                hand = make_hand(state, rng)
                features = normalize_landmarks(hand)
                writer.writerow(features.tolist() + [label])
                rows_written += 1

    print(f"Wrote {rows_written} rows to {args.out}")
    print(f"Classes: {len(STATE_TO_LABEL)}")


if __name__ == "__main__":
    main()
