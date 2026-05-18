#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = PROJECT_ROOT / "third_party"
GESTURE_REPO = THIRD_PARTY / "Sign-Language-Interpreter-using-Deep-Learning"
MODEL_NAME = "cnn_model_keras2.h5"


def run(cmd: list[str], cwd: Path | None = None):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def ensure_repo():
    THIRD_PARTY.mkdir(parents=True, exist_ok=True)
    if GESTURE_REPO.exists():
        print(f"[ok] gesture repo exists: {GESTURE_REPO}")
        return
    run(["git", "clone", "https://github.com/harshbg/Sign-Language-Interpreter-using-Deep-Learning.git", str(GESTURE_REPO)])


def ensure_venv(venv_path: Path):
    if not venv_path.exists():
        run([sys.executable, "-m", "venv", str(venv_path)])

    pip = venv_path / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    run([str(pip), "install", "--upgrade", "pip"])
    run([str(pip), "install", "-r", str(PROJECT_ROOT / "requirements.txt")])


def maybe_download_model(model_path: Path):
    if model_path.exists():
        return

    model_url = os.environ.get("GESTURE_MODEL_URL", "").strip()
    if not model_url:
        print("[warn] pretrained model is missing and GESTURE_MODEL_URL is not set")
        return

    import urllib.request

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[info] downloading model from {model_url}")
    urllib.request.urlretrieve(model_url, str(model_path))


def write_env_file(code_dir: Path):
    env_file = PROJECT_ROOT / ".env"
    lines = [
        f"GESTURE_REPO_ROOT={GESTURE_REPO}",
        f"GESTURE_MODEL_PATH={code_dir / MODEL_NAME}",
        f"GESTURE_HIST_PATH={code_dir / 'hist'}",
        f"GESTURE_DB_PATH={code_dir / 'gesture_db.db'}",
        f"GESTURES_DIR={code_dir / 'gestures'}",
        "SPOKEN_LOG_FILE=logs/spoken_sentences.log",
    ]

    desktop_req = Path.home() / "Desktop" / "requirements"
    if desktop_req.exists():
        lines.append(f"DESKTOP_REQUIREMENTS_DIR={desktop_req}")

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ok] wrote {env_file}")


def print_next_steps(code_dir: Path):
    model_path = code_dir / MODEL_NAME
    print("\n=== SETUP SUMMARY ===")
    print(f"OS: {platform.system()} {platform.release()}")
    print(f"Repo: {GESTURE_REPO}")
    print(f"Hist: {'OK' if (code_dir / 'hist').exists() else 'MISSING'}")
    print(f"DB: {'OK' if (code_dir / 'gesture_db.db').exists() else 'MISSING'}")
    print(f"Model: {'OK' if model_path.exists() else 'MISSING'}")

    if not model_path.exists():
        print("\n[blocking] Missing cnn_model_keras2.h5")
        print("Set GESTURE_MODEL_URL and rerun bootstrap, or place the model at:")
        print(model_path)
    else:
        print("\nRun:")
        if os.name == "nt":
            print(r".venv\\Scripts\\python -m app.main")
        else:
            print("source .venv/bin/activate && python -m app.main")


def main():
    os.chdir(PROJECT_ROOT)
    ensure_repo()

    venv_path = PROJECT_ROOT / ".venv"
    ensure_venv(venv_path)

    code_dir = GESTURE_REPO / "Code"
    maybe_download_model(code_dir / MODEL_NAME)
    write_env_file(code_dir)
    print_next_steps(code_dir)


if __name__ == "__main__":
    main()
