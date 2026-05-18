from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    project_root: Path
    repo_root: Path
    repo_code_dir: Path
    desktop_requirements_dir: Optional[Path]
    model_path: Path
    histogram_path: Path
    gesture_db_path: Path
    gestures_dir: Path
    camera_index_primary: int = 0
    camera_index_fallback: int = 1
    frame_width: int = 640
    frame_height: int = 480
    roi_x: int = 300
    roi_y: int = 100
    roi_w: int = 300
    roi_h: int = 300
    min_contour_area: int = 10000
    confidence_threshold: float = 0.70
    stable_frames_required: int = 15
    debounce_cooldown_frames: int = 8
    space_gesture_label: str = "Best of Luck"
    clear_gesture_label: str = "C"
    speak_gesture_label: Optional[str] = None
    spoken_log_file: Optional[Path] = None


def _env_path(name: str) -> Optional[Path]:
    val = os.environ.get(name)
    return Path(val).expanduser().resolve() if val else None


def _find_default_desktop_requirements() -> Optional[Path]:
    candidates = [
        Path.home() / "Desktop" / "requirements",
        Path.home() / "requirements",
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()
    return None


def load_config() -> AppConfig:
    project_root = Path(__file__).resolve().parents[1]

    repo_root = _env_path("GESTURE_REPO_ROOT") or (project_root / "third_party" / "Sign-Language-Interpreter-using-Deep-Learning")
    repo_code_dir = repo_root / "Code"

    model_path = _env_path("GESTURE_MODEL_PATH") or (repo_code_dir / "cnn_model_keras2.h5")
    histogram_path = _env_path("GESTURE_HIST_PATH") or (repo_code_dir / "hist")
    gesture_db_path = _env_path("GESTURE_DB_PATH") or (repo_code_dir / "gesture_db.db")
    gestures_dir = _env_path("GESTURES_DIR") or (repo_code_dir / "gestures")

    desktop_requirements = _env_path("DESKTOP_REQUIREMENTS_DIR") or _find_default_desktop_requirements()

    spoken_log_raw = os.environ.get("SPOKEN_LOG_FILE", "").strip()
    spoken_log_file = Path(spoken_log_raw).expanduser().resolve() if spoken_log_raw else (project_root / "logs" / "spoken_sentences.log")

    return AppConfig(
        project_root=project_root,
        repo_root=repo_root,
        repo_code_dir=repo_code_dir,
        desktop_requirements_dir=desktop_requirements,
        model_path=model_path,
        histogram_path=histogram_path,
        gesture_db_path=gesture_db_path,
        gestures_dir=gestures_dir,
        spoken_log_file=spoken_log_file,
    )
