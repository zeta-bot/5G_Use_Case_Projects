#!/usr/bin/env python3
"""Build an augmented landmark CSV for the 20-phrase vocabulary from combined training data."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Filter + augment phrase-only gesture CSV")
    p.add_argument("--source", type=Path, default=Path("data/gestures_combined.csv"))
    p.add_argument("--vocab", type=Path, default=Path("data/phrases20_vocab.txt"))
    p.add_argument("--out", type=Path, default=Path("data/gestures_phrases20.csv"))
    p.add_argument("--per-class", type=int, default=800, help="Target rows per class after augmentation")
    p.add_argument("--noise", type=float, default=0.014, help="Gaussian noise std on normalized landmarks")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def load_labels(path: Path) -> list[str]:
    labels: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        labels.append(line.strip().upper().replace(" ", "_"))
    return list(dict.fromkeys(labels))


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    wanted = load_labels(args.vocab)
    if len(wanted) != 20:
        raise SystemExit(f"Expected 20 labels in vocab, got {len(wanted)}")

    df = pd.read_csv(args.source)
    if "label" not in df.columns:
        raise SystemExit("CSV must have a label column")
    df["label"] = df["label"].astype(str).str.strip().str.upper().str.replace(" ", "_", regex=False)

    missing = [l for l in wanted if l not in set(df["label"].unique())]
    if missing:
        raise SystemExit(f"Labels not in source data: {missing}")

    sub = df[df["label"].isin(wanted)].copy()
    feature_cols = [c for c in sub.columns if c != "label"]
    if len(feature_cols) != 63:
        raise SystemExit(f"Need 63 feature columns, got {len(feature_cols)}")

    rows: list[np.ndarray] = []
    labels: list[str] = []

    for label in wanted:
        g = sub[sub["label"] == label]
        arr = g[feature_cols].to_numpy(dtype=np.float64)
        n_real = len(arr)
        if n_real == 0:
            raise SystemExit(f"No rows for {label}")

        for _ in range(args.per_class):
            idx = int(rng.integers(0, n_real))
            feat = arr[idx].copy()
            feat += rng.normal(0.0, args.noise, size=feat.shape)
            rows.append(feat.astype(np.float32))
            labels.append(label)

    out_df = pd.DataFrame(np.vstack(rows), columns=feature_cols)
    out_df["label"] = labels
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out, index=False)

    vc = out_df["label"].value_counts().sort_index()
    print(f"Wrote {len(out_df)} rows to {args.out}")
    print(vc.to_string())


if __name__ == "__main__":
    main()
