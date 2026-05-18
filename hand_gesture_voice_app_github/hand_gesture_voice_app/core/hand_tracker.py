from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import cv2

# Force CPU mode for better compatibility across macOS/OpenGL setups.
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
import mediapipe as mp
import numpy as np


@dataclass
class HandTrackResult:
    frame: np.ndarray
    landmarks_3d: Optional[np.ndarray]
    normalized_features: Optional[np.ndarray]


class HandTracker:
    """MediaPipe Hands wrapper for real-time landmark extraction."""

    def __init__(
        self,
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.5,
    ):
        if not hasattr(mp, "solutions"):
            raise RuntimeError(
                "Incompatible MediaPipe build detected (missing mp.solutions). "
                "Install a solutions-compatible version: pip install 'mediapipe==0.10.9'."
            )
        self._mp_hands = mp.solutions.hands
        self._mp_draw = mp.solutions.drawing_utils
        self._mp_styles = mp.solutions.drawing_styles

        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_num_hands,
            model_complexity=0,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def _normalize_landmarks(self, landmarks_xyz: np.ndarray) -> np.ndarray:
        # Translation invariance: wrist (landmark 0) at origin.
        wrist = landmarks_xyz[0]
        centered = landmarks_xyz - wrist

        # Scale invariance: normalize by max radial distance from wrist.
        scale = np.linalg.norm(centered, axis=1).max()
        scale = max(scale, 1e-6)
        normalized = centered / scale

        return normalized.reshape(-1).astype(np.float32)

    def process(self, frame_bgr: np.ndarray) -> HandTrackResult:
        frame = cv2.flip(frame_bgr, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._hands.process(frame_rgb)

        if not results.multi_hand_landmarks:
            return HandTrackResult(frame=frame, landmarks_3d=None, normalized_features=None)

        hand_landmarks = results.multi_hand_landmarks[0]
        self._mp_draw.draw_landmarks(
            frame,
            hand_landmarks,
            self._mp_hands.HAND_CONNECTIONS,
            self._mp_styles.get_default_hand_landmarks_style(),
            self._mp_styles.get_default_hand_connections_style(),
        )

        landmarks_xyz = np.array(
            [[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark], dtype=np.float32
        )
        normalized_features = self._normalize_landmarks(landmarks_xyz)

        return HandTrackResult(
            frame=frame,
            landmarks_3d=landmarks_xyz,
            normalized_features=normalized_features,
        )

    def close(self) -> None:
        self._hands.close()
