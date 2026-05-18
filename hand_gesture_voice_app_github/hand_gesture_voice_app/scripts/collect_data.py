from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.hand_tracker import HandTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect normalized hand landmark data")
    parser.add_argument("--label", required=True, type=str, help="Gesture label to record")
    parser.add_argument("--out", type=Path, default=Path("data/gestures.csv"))
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--camera-index", type=int, default=0)
    return parser.parse_args()


def ensure_header(csv_path: Path) -> None:
    if csv_path.exists() and csv_path.stat().st_size > 0:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    header = [f"f{i}" for i in range(63)] + ["label"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)


def main() -> None:
    args = parse_args()
    ensure_header(args.out)

    tracker = HandTracker()
    cap = cv2.VideoCapture(args.camera_index)
    if not cap.isOpened():
        raise RuntimeError("Unable to open webcam")

    collected = 0
    window = "Collect Gesture Data"

    print(f"Collecting label='{args.label}'")
    print("Press 'r' to record sample when hand is detected, 'q' to quit.")

    try:
        with args.out.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            while collected < args.samples:
                ok, frame = cap.read()
                if not ok:
                    continue

                result = tracker.process(frame)
                overlay = result.frame.copy()
                cv2.putText(
                    overlay,
                    f"Label: {args.label} | Collected: {collected}/{args.samples}",
                    (14, 32),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    overlay,
                    "r: record | q: quit",
                    (14, 62),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

                cv2.imshow(window, overlay)
                key = cv2.waitKey(1) & 0xFF

                if key == ord("q"):
                    break
                if key == ord("r") and result.normalized_features is not None:
                    row = result.normalized_features.tolist() + [args.label]
                    writer.writerow(row)
                    collected += 1

        print(f"Saved samples to {args.out}")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()


if __name__ == "__main__":
    main()
