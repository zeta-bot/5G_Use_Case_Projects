from __future__ import annotations

import cv2
import numpy as np


def _draw_text(frame: np.ndarray, text: str, y: int, color=(255, 255, 255), scale: float = 0.7) -> None:
    cv2.putText(
        frame,
        text,
        (14, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        2,
        cv2.LINE_AA,
    )


def get_delete_button_rect(width: int) -> tuple[int, int, int, int]:
    """Returns (x1, y1, x2, y2) for the clickable DELETE button."""
    margin = 16
    btn_w = 140
    btn_h = 40
    x2 = width - margin
    x1 = max(margin, x2 - btn_w)
    y1 = 20
    y2 = y1 + btn_h
    return x1, y1, x2, y2


def render_ui(
    frame: np.ndarray,
    label: str,
    confidence: float,
    sentence: str,
    fps: float,
    mode: str,
    tts_backend: str,
    green_sample_border: bool = False,
) -> np.ndarray:
    canvas = frame.copy()

    h, w = canvas.shape[:2]
    cv2.rectangle(canvas, (8, 8), (w - 8, 160), (20, 20, 20), -1)
    cv2.rectangle(canvas, (8, h - 80), (w - 8, h - 8), (20, 20, 20), -1)

    # Mouse-clickable DELETE button (undo last committed segment).
    x1, y1, x2, y2 = get_delete_button_rect(w)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (60, 60, 60), -1)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (180, 180, 180), 2)
    cv2.putText(
        canvas,
        "DELETE",
        (x1 + 18, y2 - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    if green_sample_border:
        t = max(6, min(h, w) // 120)
        cv2.rectangle(canvas, (0, 0), (w - 1, h - 1), (0, 255, 0), thickness=t)

    detected = label if label else "-"
    status_color = (0, 255, 0) if green_sample_border else (0, 255, 255)
    _draw_text(canvas, f"Gesture: {detected}", 40, status_color, 0.8)
    _draw_text(canvas, f"Confidence: {confidence:.2f}", 70, (0, 220, 180), 0.7)
    _draw_text(canvas, f"Mode: {mode} | FPS: {fps:.1f}", 100, (255, 255, 255), 0.7)
    _draw_text(canvas, f"TTS: {tts_backend}", 130, (200, 200, 255), 0.7)

    sentence_preview = sentence[-70:] if len(sentence) > 70 else sentence
    _draw_text(canvas, f"Sentence: {sentence_preview}", h - 32, (255, 255, 255), 0.75)

    return canvas
