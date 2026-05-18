from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.gesture_model import GestureClassifier
from core.hand_tracker import HandTracker


@dataclass
class InferenceResult:
    frame: np.ndarray
    label: str
    confidence: float
    has_hand: bool


class InferencePipeline:
    def __init__(
        self,
        model_path: Path,
        labels_path: Path,
    ):
        self.hand_tracker = HandTracker()
        self.classifier = GestureClassifier(model_path=model_path, labels_path=labels_path)

    def run_frame(self, frame: np.ndarray) -> InferenceResult:
        tracked = self.hand_tracker.process(frame)
        label, confidence = self.classifier.predict(tracked.normalized_features)

        return InferenceResult(
            frame=tracked.frame,
            label=label,
            confidence=confidence,
            has_hand=tracked.normalized_features is not None,
        )

    def close(self) -> None:
        self.hand_tracker.close()
