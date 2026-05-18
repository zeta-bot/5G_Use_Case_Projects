from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from gesture.model_loader import get_image_size, load_gesture_labels, load_trained_model
from gesture.preprocess import extract_hand_patch, get_img_contour_thresh, load_hand_hist


@dataclass
class PredictionResult:
    frame: np.ndarray
    thresh: np.ndarray
    label: str
    confidence: float
    class_id: Optional[int]
    contour_area: float


class GestureDetector:
    def __init__(
        self,
        model_path,
        histogram_path,
        gesture_db_path,
        gestures_dir,
        roi: Tuple[int, int, int, int],
        min_contour_area: int = 10000,
        confidence_threshold: float = 0.70,
    ):
        self.model = load_trained_model(model_path)
        self.hist = load_hand_hist(histogram_path)
        self.labels: Dict[int, str] = load_gesture_labels(gesture_db_path)
        self.image_x, self.image_y = get_image_size(gestures_dir)

        self.roi = roi
        self.min_contour_area = min_contour_area
        self.confidence_threshold = confidence_threshold

        # Warmup to avoid initial latency spike.
        warm = np.zeros((1, self.image_x, self.image_y, 1), dtype=np.float32)
        self.model.predict(warm, verbose=0)

    def _keras_process_image(self, img: np.ndarray) -> np.ndarray:
        img = cv2.resize(img, (self.image_x, self.image_y))
        img = np.array(img, dtype=np.float32)
        img = np.reshape(img, (1, self.image_x, self.image_y, 1))
        return img

    def _predict_from_patch(self, patch: np.ndarray):
        processed = self._keras_process_image(patch)
        pred_probab = self.model.predict(processed, verbose=0)[0]
        pred_class = int(np.argmax(pred_probab))
        confidence = float(np.max(pred_probab))
        return confidence, pred_class

    def predict(self, frame: np.ndarray) -> PredictionResult:
        img, contours, thresh = get_img_contour_thresh(frame, self.hist, self.roi)

        label = ""
        confidence = 0.0
        class_id: Optional[int] = None
        area = 0.0

        if contours:
            contour = max(contours, key=cv2.contourArea)
            area = float(cv2.contourArea(contour))
            if area > self.min_contour_area:
                hand_patch = extract_hand_patch(contour, thresh)
                confidence, class_id = self._predict_from_patch(hand_patch)
                if confidence >= self.confidence_threshold:
                    label = self.labels.get(class_id, "")

        return PredictionResult(
            frame=img,
            thresh=thresh,
            label=label,
            confidence=confidence,
            class_id=class_id,
            contour_area=area,
        )
