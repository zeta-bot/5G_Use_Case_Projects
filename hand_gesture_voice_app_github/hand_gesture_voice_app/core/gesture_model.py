from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import joblib
import numpy as np


class RuleBasedClassifier:
    """Fast fallback classifier for a small gesture vocabulary.

    Labels:
    - HELLO, YES, NO, THANKS
    - PLEASE, SORRY, HELP, I, YOU, WE, GO, STOP, WATER, FOOD, LOVE, WANT, NEED
    - I_NEED_WATER, I_NEED_FOOD
    - SPACE, DELETE, CLEAR, SPEAK
    """

    def __init__(self):
        self.labels = [
            "HELLO",
            "YES",
            "NO",
            "THANKS",
            "PLEASE",
            "SORRY",
            "HELP",
            "I",
            "YOU",
            "WE",
            "GO",
            "STOP",
            "WATER",
            "FOOD",
            "LOVE",
            "WANT",
            "NEED",
            "I_NEED_WATER",
            "I_NEED_FOOD",
            "SPACE",
            "DELETE",
            "CLEAR",
            "SPEAK",
        ]

    @staticmethod
    def _finger_is_open(hand: np.ndarray, tip_idx: int, pip_idx: int) -> bool:
        # In normalized coordinates, smaller y is visually higher (upright finger).
        return hand[tip_idx, 1] < hand[pip_idx, 1]

    def predict(self, features: np.ndarray) -> Tuple[str, float]:
        hand = features.reshape(21, 3)

        thumb_tip_dist = float(np.linalg.norm(hand[4, :2] - hand[0, :2]))
        thumb_ip_dist = float(np.linalg.norm(hand[3, :2] - hand[0, :2]))
        thumb_open = thumb_tip_dist > (thumb_ip_dist * 1.10)
        index_open = self._finger_is_open(hand, 8, 6)
        middle_open = self._finger_is_open(hand, 12, 10)
        ring_open = self._finger_is_open(hand, 16, 14)
        pinky_open = self._finger_is_open(hand, 20, 18)

        state = (
            int(thumb_open),
            int(index_open),
            int(middle_open),
            int(ring_open),
            int(pinky_open),
        )

        # Exact state map avoids overlapping conditions and makes gesture behavior stable.
        state_map = {
            (0, 0, 0, 0, 0): ("SPEAK", 0.70),
            (1, 1, 1, 1, 1): ("HELLO", 0.72),
            (0, 1, 0, 0, 0): ("YES", 0.67),
            (0, 1, 1, 0, 0): ("NO", 0.67),
            (0, 0, 1, 1, 1): ("THANKS", 0.65),
            (0, 1, 0, 0, 1): ("SPACE", 0.66),
            (1, 0, 0, 0, 1): ("DELETE", 0.66),
            (1, 1, 0, 0, 0): ("CLEAR", 0.66),
            (0, 0, 1, 0, 0): ("PLEASE", 0.64),
            (0, 0, 0, 1, 0): ("SORRY", 0.64),
            (0, 0, 0, 0, 1): ("HELP", 0.64),
            (1, 0, 0, 0, 0): ("I", 0.63),
            (0, 1, 0, 1, 0): ("YOU", 0.63),
            (0, 0, 1, 0, 1): ("WE", 0.63),
            (0, 0, 0, 1, 1): ("GO", 0.63),
            (1, 0, 1, 0, 0): ("STOP", 0.63),
            (1, 0, 0, 1, 0): ("WATER", 0.63),
            (1, 0, 1, 1, 0): ("FOOD", 0.62),
            (1, 1, 1, 0, 0): ("LOVE", 0.62),
            (0, 1, 1, 1, 0): ("WANT", 0.62),
            (0, 1, 1, 0, 1): ("NEED", 0.62),
            (0, 1, 1, 1, 1): ("I_NEED_WATER", 0.61),
            (1, 1, 1, 1, 0): ("I_NEED_FOOD", 0.61),
        }

        if state in state_map:
            return state_map[state]

        return "", 0.0


class GestureClassifier:
    def __init__(self, model_path: Path, labels_path: Path):
        self.model_path = model_path
        self.labels_path = labels_path
        self.model = None
        self.id_to_label: Dict[int, str] = {}
        self.rule_based = RuleBasedClassifier()

        self._load_if_available()

    @property
    def has_model(self) -> bool:
        return self.model is not None and bool(self.id_to_label)

    def _load_if_available(self) -> None:
        if not self.model_path.exists() or not self.labels_path.exists():
            return

        self.model = joblib.load(self.model_path)
        raw = json.loads(self.labels_path.read_text(encoding="utf-8"))
        self.id_to_label = {int(k): str(v) for k, v in raw.items()}

    def _predict_model(self, features: np.ndarray) -> Tuple[str, float]:
        assert self.model is not None
        probs = self.model.predict_proba(features.reshape(1, -1))[0]
        best_idx = int(np.argmax(probs))
        confidence = float(probs[best_idx])
        label = self.id_to_label.get(best_idx, "")
        return label, confidence

    def predict(self, features: Optional[np.ndarray]) -> Tuple[str, float]:
        if features is None:
            return "", 0.0

        if self.has_model:
            return self._predict_model(features)

        return self.rule_based.predict(features)
