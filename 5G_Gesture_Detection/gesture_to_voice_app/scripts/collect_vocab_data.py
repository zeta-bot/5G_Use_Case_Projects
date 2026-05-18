from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.hand_tracker import HandTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided multi-label hand landmark data collection")
    parser.add_argument("--vocab-file", type=Path, default=Path("data/common_words_100.txt"))
    parser.add_argument("--out", type=Path, default=Path("data/gestures.csv"))
    parser.add_argument("--samples-per-label", type=int, default=200)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--start-label", type=str, default=None)
    parser.add_argument("--auto-next", action="store_true", help="Auto-advance after target reached")
    return parser.parse_args()


def normalize_label(label: str) -> str:
    return label.strip().upper().replace(" ", "_")


def load_labels(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Vocab file not found: {path}")

    labels: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        labels.append(normalize_label(line))

    if not labels:
        raise ValueError("No labels found in vocab file")

    deduped = list(dict.fromkeys(labels))
    return deduped


def ensure_header(csv_path: Path) -> None:
    if csv_path.exists() and csv_path.stat().st_size > 0:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    header = [f"f{i}" for i in range(63)] + ["label"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)


def load_counts(csv_path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return counts

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = normalize_label(row.get("label", ""))
            if label:
                counts[label] += 1
    return counts


def main() -> None:
    args = parse_args()
    labels = load_labels(args.vocab_file)
    ensure_header(args.out)

    counts = load_counts(args.out)
    tracker = HandTracker()
    cap = cv2.VideoCapture(args.camera_index)
    if not cap.isOpened():
        raise RuntimeError("Unable to open webcam")

    idx = 0
    if args.start_label:
        normalized_start = normalize_label(args.start_label)
        if normalized_start in labels:
            idx = labels.index(normalized_start)

    window = "Collect Vocab Data"

    print(f"Loaded {len(labels)} labels from {args.vocab_file}")
    print("Controls: SPACE=record, n=next label, p=prev label, q=quit (r also works)")

    try:
        with args.out.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            while 0 <= idx < len(labels):
                label = labels[idx]
                current = counts[label]
                target = args.samples_per_label

                ok, frame = cap.read()
                if not ok:
                    continue

                result = tracker.process(frame)
                overlay = result.frame.copy()

                cv2.putText(
                    overlay,
                    f"Label {idx + 1}/{len(labels)}: {label}",
                    (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    overlay,
                    f"Samples: {current}/{target}",
                    (12, 64),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 220, 180),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    overlay,
                    "SPACE=record n=next p=prev q=quit",
                    (12, 96),
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
                if key == ord("n"):
                    idx = min(idx + 1, len(labels) - 1)
                    continue
                if key == ord("p"):
                    idx = max(idx - 1, 0)
                    continue
                if key in (ord(" "), ord("r")) and result.normalized_features is not None:
                    row = result.normalized_features.tolist() + [label]
                    writer.writerow(row)
                    counts[label] += 1
                    current = counts[label]

                if args.auto_next and current >= target and idx < len(labels) - 1:
                    idx += 1

        print(f"Saved data to: {args.out}")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        tracker.close()


if __name__ == "__main__":
    main()
