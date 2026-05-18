from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.buffer import SentenceBuffer
from app.ui import get_delete_button_rect, render_ui
from core.inference import InferencePipeline, InferenceResult
from tts.engine import TTSEngine


def normalize_camera_source(camera_source: str) -> str:
    source = camera_source.strip()
    if source.startswith("rtsp:/") and not source.startswith("rtsp://"):
        return source.replace("rtsp:/", "rtsp://", 1)
    if source.startswith("rtsps:/") and not source.startswith("rtsps://"):
        return source.replace("rtsps:/", "rtsps://", 1)
    return source


def parse_camera_source(args: argparse.Namespace) -> int | str:
    raw = args.camera_source if args.camera_source is not None else str(args.camera_index)
    raw = normalize_camera_source(raw)
    if raw.isdigit():
        return int(raw)
    return raw


def open_camera(source: int | str, args: argparse.Namespace) -> cv2.VideoCapture:
    # Prefer FFmpeg for network streams and set RTSP transport explicitly.
    if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            f"rtsp_transport;{args.rtsp_transport}|stimeout;{int(args.open_timeout_ms) * 1000}"
        )
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(source)

    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, float(args.open_timeout_ms))
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, float(args.read_timeout_ms))

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    return cap


def run(args: argparse.Namespace) -> None:
    model_path = PROJECT_ROOT / "models" / "gesture_model.pkl"
    labels_path = PROJECT_ROOT / "models" / "labels.json"
    spoken_log = PROJECT_ROOT / "data" / "spoken_log.txt"

    pipeline = InferencePipeline(
        model_path=model_path,
        labels_path=labels_path,
    )
    if pipeline.classifier.has_model:
        print(f"[MODEL] Using trained MLP model: {model_path}")
    else:
        msg = "[MODEL] No trained model found. Using rule-based fallback."
        if args.require_mlp:
            raise RuntimeError(
                f"{msg} Expected files: {model_path} and {labels_path}. "
                "Train first, then rerun."
            )
        print(msg)
    buffer = SentenceBuffer(
        stable_frames=args.stable_frames,
        cooldown_frames=args.cooldown_frames,
        mode=args.mode,
        word_map_path=Path(args.word_map) if args.word_map else None,
    )
    tts = TTSEngine(
        voice_id=args.voice,
        spoken_log_file=spoken_log,
        preferred_backend=args.tts_backend,
        strict_preferred=not args.allow_tts_fallback,
    )
    print(f"[TTS] Active backend: {tts.backend.name}")
    print(f"[TTS] Press 'v' to toggle between {args.tts_toggle_primary} and {args.tts_fallback_backend}.")
    if args.list_voices:
        voices = tts.list_voices()
        if not voices:
            print(f"No explicit voices exposed by backend '{tts.backend.name}'.")
        else:
            print(f"Backend: {tts.backend.name}")
            for voice in voices:
                print(f"- {voice.id} ({voice.name})")
        tts.shutdown()
        return

    camera_source = parse_camera_source(args)
    cap = open_camera(camera_source, args)

    if not cap.isOpened():
        raise RuntimeError(
            f"Unable to open camera source: {camera_source}. "
            "Try --camera-source 0 or --camera-source <rtsp-url>."
        )

    fps = 0.0
    last = time.perf_counter()
    last_infer_at = 0.0
    last_result: InferenceResult | None = None
    sample_border_until = 0.0

    window_name = "Real-Time Hand Gesture To Voice"
    cv2.namedWindow(window_name)

    mouse_state = {"clicked": False, "x": 0, "y": 0}

    def _on_mouse(event, x, y, flags, userdata) -> None:  # type: ignore[no-untyped-def]
        _ = flags, userdata
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse_state["clicked"] = True
            mouse_state["x"] = int(x)
            mouse_state["y"] = int(y)

    cv2.setMouseCallback(window_name, _on_mouse)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            live_mirror = cv2.flip(frame, 1)
            now = time.perf_counter()
            due_infer = last_infer_at == 0.0 or (now - last_infer_at) >= args.infer_interval_sec

            if due_infer:
                result = pipeline.run_frame(frame)
                last_result = result
                last_infer_at = now
                sample_border_until = now + args.sample_border_sec
                event = buffer.update(result.label)

                if event.speak_requested and buffer.sentence.strip():
                    tts.speak_async(buffer.sentence)
                display_frame = result.frame
            else:
                display_frame = live_mirror

            dt = max(now - last, 1e-6)
            fps = (0.9 * fps + 0.1 * (1.0 / dt)) if fps else (1.0 / dt)
            last = now

            label_txt = last_result.label if last_result else ""
            conf_txt = last_result.confidence if last_result else 0.0
            green_border = now < sample_border_until

            ui = render_ui(
                frame=display_frame,
                label=label_txt,
                confidence=conf_txt,
                sentence=buffer.sentence,
                fps=fps,
                mode=buffer.mode,
                tts_backend=tts.backend.name,
                green_sample_border=green_border,
            )

            if mouse_state["clicked"]:
                x1, y1, x2, y2 = get_delete_button_rect(ui.shape[1])
                x = mouse_state["x"]
                y = mouse_state["y"]
                if x1 <= x <= x2 and y1 <= y <= y2:
                    buffer.delete_last()
                mouse_state["clicked"] = False

            cv2.imshow(window_name, ui)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            if key == ord("s") and buffer.sentence.strip():
                tts.speak_async(buffer.sentence)
            if key == ord("s") and not buffer.sentence.strip():
                print("[TTS] Sentence is empty. Add text first, or press 't' for a test phrase.")
            if key == ord("c"):
                buffer.clear()
            if key == ord("m"):
                next_mode = "char" if buffer.mode == "word" else "word"
                buffer.set_mode(next_mode)
            if key == ord("t"):
                tts.speak_async("Audio test successful")
            if key == ord("v"):
                new_backend = tts.toggle_between(args.tts_toggle_primary, args.tts_fallback_backend)
                print(f"[TTS] Switched backend to: {new_backend}")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        pipeline.close()
        tts.shutdown()


def parse_args() -> argparse.Namespace:
    env_tts_backend = os.getenv("TTS_BACKEND", "pyttsx3").strip().lower()
    if env_tts_backend == "kokuro":
        env_tts_backend = "kokoro"
    if env_tts_backend not in {"auto", "kokoro", "coqui", "pyttsx3", "say"}:
        env_tts_backend = "pyttsx3"

    env_allow_fallback = os.getenv("ALLOW_TTS_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
    env_tts_toggle_primary = os.getenv("TTS_TOGGLE_PRIMARY", env_tts_backend).strip().lower()
    env_tts_fallback_backend = os.getenv("TTS_FALLBACK_BACKEND", "pyttsx3").strip().lower()
    if env_tts_toggle_primary == "kokuro":
        env_tts_toggle_primary = "kokoro"
    if env_tts_toggle_primary not in {"kokoro", "coqui", "pyttsx3", "say"}:
        env_tts_toggle_primary = "pyttsx3"
    if env_tts_fallback_backend not in {"pyttsx3", "say", "coqui"}:
        env_tts_fallback_backend = "pyttsx3"

    parser = argparse.ArgumentParser(description="Webcam gesture to voice application")
    parser.add_argument(
        "--camera-source",
        type=str,
        default=os.getenv("CAMERA_SOURCE"),
        help="Camera source index or stream URL (e.g. 0, rtsp://user:pass@host:554/path).",
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--rtsp-transport", choices=["tcp", "udp"], default="tcp")
    parser.add_argument("--open-timeout-ms", type=int, default=8000)
    parser.add_argument("--read-timeout-ms", type=int, default=8000)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument(
        "--infer-interval-sec",
        type=float,
        default=3.0,
        help="Run hand tracking + gesture inference at most once per this many seconds (live preview every frame).",
    )
    parser.add_argument(
        "--sample-border-sec",
        type=float,
        default=0.35,
        help="Keep the green border visible this long after each captured frame (easier to see than a single video frame).",
    )
    parser.add_argument(
        "--require-mlp",
        action="store_true",
        help="Fail startup unless trained MLP files exist (models/gesture_model.pkl + models/labels.json).",
    )
    parser.add_argument(
        "--stable-frames",
        type=int,
        default=1,
        help="Consecutive inference samples with the same label required to commit (inference runs every --infer-interval-sec).",
    )
    parser.add_argument("--cooldown-frames", type=int, default=1)
    parser.add_argument("--mode", choices=["word", "char"], default="word")
    parser.add_argument(
        "--word-map",
        type=str,
        default=None,
        help="Optional JSON map of MODEL_LABEL -> output phrase (e.g., I_NEED_WATER -> I need water).",
    )
    parser.add_argument("--voice", type=str, default=None)
    parser.add_argument("--list-voices", action="store_true")
    parser.add_argument(
        "--tts-backend",
        choices=["auto", "kokoro", "kokuro", "coqui", "pyttsx3", "say"],
        default=env_tts_backend,
    )
    parser.add_argument(
        "--allow-tts-fallback",
        action="store_true",
        default=env_allow_fallback,
        help="Allow fallback to another backend if requested backend is unavailable.",
    )
    parser.add_argument(
        "--tts-fallback-backend",
        choices=["pyttsx3", "say", "coqui"],
        default=env_tts_fallback_backend,
        help="Fallback backend used by the live TTS toggle key ('v').",
    )
    parser.add_argument(
        "--tts-toggle-primary",
        choices=["kokoro", "coqui", "pyttsx3", "say"],
        default=env_tts_toggle_primary,
        help="Primary backend used by the live TTS toggle key ('v').",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
