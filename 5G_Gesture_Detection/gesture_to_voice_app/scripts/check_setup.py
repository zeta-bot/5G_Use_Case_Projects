#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import load_config


def status(path: Path) -> str:
    return "OK" if path.exists() else "MISSING"


def main():
    cfg = load_config()
    print(f"Project root: {cfg.project_root}")
    print(f"Repo root: {cfg.repo_root}")
    print(f"Model: {cfg.model_path} -> {status(cfg.model_path)}")
    print(f"Histogram: {cfg.histogram_path} -> {status(cfg.histogram_path)}")
    print(f"Gesture DB: {cfg.gesture_db_path} -> {status(cfg.gesture_db_path)}")
    print(f"Gestures dir: {cfg.gestures_dir} -> {status(cfg.gestures_dir)}")
    print(f"Desktop requirements dir: {cfg.desktop_requirements_dir}")


if __name__ == "__main__":
    main()
