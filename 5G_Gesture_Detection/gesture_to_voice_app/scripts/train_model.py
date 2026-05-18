from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import LabelEncoder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train MLP gesture model from landmark CSV data")
    parser.add_argument("--data", type=Path, default=Path("data/gestures.csv"))
    parser.add_argument("--vocab-file", type=Path, default=Path("data/common_words_100.txt"))
    parser.add_argument("--model-out", type=Path, default=Path("models/gesture_model.pkl"))
    parser.add_argument("--labels-out", type=Path, default=Path("models/labels.json"))
    parser.add_argument("--report-out", type=Path, default=Path("models/training_report.txt"))
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--min-samples-per-class", type=int, default=60)
    parser.add_argument(
        "--hidden-layers",
        type=str,
        default="256,128",
        help='MLP hidden sizes, comma-separated (e.g. "512,256,128").',
    )
    parser.add_argument("--max-iter", type=int, default=400)
    parser.add_argument("--mlp-alpha", type=float, default=1e-4)
    return parser.parse_args()


def normalize_label(label: str) -> str:
    return str(label).strip().upper().replace(" ", "_")


def load_vocab(path: Path) -> list[str]:
    if not path.exists():
        return []
    labels: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        labels.append(normalize_label(line))
    return list(dict.fromkeys(labels))


def main() -> None:
    args = parse_args()

    if not args.data.exists():
        raise FileNotFoundError(
            f"Dataset not found: {args.data}. Expected CSV with 63 feature columns and a 'label' column."
        )

    df = pd.read_csv(args.data)
    if "label" not in df.columns:
        raise ValueError("CSV must include a 'label' column")

    feature_cols = [col for col in df.columns if col != "label"]
    if len(feature_cols) != 63:
        raise ValueError(f"Expected 63 landmark features, got {len(feature_cols)}")

    X = df[feature_cols].to_numpy(dtype=np.float32)
    y_raw = df["label"].astype(str).map(normalize_label).to_numpy()

    class_counts = pd.Series(y_raw).value_counts().sort_index()
    low_count = class_counts[class_counts < args.min_samples_per_class]
    if not low_count.empty:
        raise ValueError(
            "Insufficient samples for some classes. "
            f"Need at least {args.min_samples_per_class} per class.\n"
            + "\n".join([f"{lbl}: {cnt}" for lbl, cnt in low_count.items()])
        )

    vocab = load_vocab(args.vocab_file)
    if vocab:
        missing = sorted(set(vocab) - set(class_counts.index))
        extras = sorted(set(class_counts.index) - set(vocab))
        if missing:
            print(f"WARNING: {len(missing)} vocab labels missing in dataset.")
            print("First missing labels:", ", ".join(missing[:20]))
        if extras:
            print(f"WARNING: {len(extras)} dataset labels not in vocab file.")
            print("First extra labels:", ", ".join(extras[:20]))

    encoder = LabelEncoder()
    y = encoder.fit_transform(y_raw)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, stratify=y
    )

    hidden = tuple(int(x.strip()) for x in args.hidden_layers.split(",") if x.strip())
    if not hidden or any(h <= 0 for h in hidden):
        raise ValueError(f"Invalid --hidden-layers: {args.hidden_layers!r}")

    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "mlp",
                MLPClassifier(
                    hidden_layer_sizes=hidden,
                    activation="relu",
                    solver="adam",
                    alpha=args.mlp_alpha,
                    batch_size=min(128, max(32, len(X_train) // 8)),
                    learning_rate_init=1e-3,
                    max_iter=args.max_iter,
                    early_stopping=True,
                    validation_fraction=0.12,
                    n_iter_no_change=30,
                    random_state=args.random_state,
                    verbose=True,
                ),
            ),
        ]
    )
    model.fit(X_train, y_train)

    acc = model.score(X_test, y_test)
    print(f"Validation accuracy: {acc:.4f}")

    y_pred = model.predict(X_test)
    report = classification_report(y_test, y_pred, target_names=encoder.classes_, digits=4, zero_division=0)
    print(report)

    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    args.labels_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, args.model_out)

    id_to_label = {int(i): label for i, label in enumerate(encoder.classes_)}
    args.labels_out.write_text(json.dumps(id_to_label, indent=2), encoding="utf-8")
    args.report_out.write_text(
        "Class counts:\\n"
        + class_counts.to_string()
        + "\\n\\nClassification report:\\n"
        + report,
        encoding="utf-8",
    )

    print(f"Saved model: {args.model_out}")
    print(f"Saved labels: {args.labels_out}")
    print(f"Saved report: {args.report_out}")


if __name__ == "__main__":
    main()
