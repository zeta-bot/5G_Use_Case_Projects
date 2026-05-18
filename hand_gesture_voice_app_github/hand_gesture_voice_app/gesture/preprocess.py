from __future__ import annotations

import pickle
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np


ROI_X, ROI_Y, ROI_W, ROI_H = 300, 100, 300, 300


def load_hand_hist(histogram_path: Path) -> np.ndarray:
    if not histogram_path.exists():
        raise FileNotFoundError(f"Histogram file not found: {histogram_path}")
    with open(histogram_path, "rb") as f:
        return pickle.load(f)


def get_img_contour_thresh(
    frame: np.ndarray,
    hist: np.ndarray,
    roi: Tuple[int, int, int, int] = (ROI_X, ROI_Y, ROI_W, ROI_H),
):
    # This function intentionally preserves the original preprocessing sequence from the source repo.
    x, y, w, h = roi
    img = cv2.flip(frame, 1)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    dst = cv2.calcBackProject([img_hsv], [0, 1], hist, [0, 180, 0, 256], 1)
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (10, 10))
    cv2.filter2D(dst, -1, disc, dst)
    blur = cv2.GaussianBlur(dst, (11, 11), 0)
    blur = cv2.medianBlur(blur, 15)

    thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    thresh = cv2.merge((thresh, thresh, thresh))
    thresh = cv2.cvtColor(thresh, cv2.COLOR_BGR2GRAY)
    thresh = thresh[y : y + h, x : x + w]

    contours = cv2.findContours(thresh.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)[0]
    return img, contours, thresh


def extract_hand_patch(contour: np.ndarray, thresh: np.ndarray) -> np.ndarray:
    x1, y1, w1, h1 = cv2.boundingRect(contour)
    save_img = thresh[y1 : y1 + h1, x1 : x1 + w1]

    # Keep the same square-padding logic as the original implementation.
    if w1 > h1:
        pad = int((w1 - h1) / 2)
        save_img = cv2.copyMakeBorder(save_img, pad, pad, 0, 0, cv2.BORDER_CONSTANT, (0, 0, 0))
    elif h1 > w1:
        pad = int((h1 - w1) / 2)
        save_img = cv2.copyMakeBorder(save_img, 0, 0, pad, pad, cv2.BORDER_CONSTANT, (0, 0, 0))

    return save_img
