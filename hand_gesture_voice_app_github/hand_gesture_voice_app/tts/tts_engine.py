from __future__ import annotations

import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class TTSBackend:
    name: str

    def speak(self, text: str):
        raise NotImplementedError


class CoquiBackend(TTSBackend):
    def __init__(self):
        super().__init__(name="coqui-tts")
        from TTS.api import TTS  # type: ignore

        self._tts = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False)

    def speak(self, text: str):
        wav = self._tts.tts(text=text)
        import numpy as np
        import sounddevice as sd

        sample_rate = 22050
        if hasattr(self._tts, "synthesizer") and hasattr(self._tts.synthesizer, "output_sample_rate"):
            sample_rate = int(self._tts.synthesizer.output_sample_rate)
        sd.play(np.array(wav, dtype=np.float32), samplerate=sample_rate)
        sd.wait()


class Pyttsx3Backend(TTSBackend):
    def __init__(self):
        super().__init__(name="pyttsx3")
        import pyttsx3

        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", 150)

    def speak(self, text: str):
        self._engine.say(text)
        self._engine.runAndWait()


class MacSayBackend(TTSBackend):
    def __init__(self):
        super().__init__(name="macos-say")

    def speak(self, text: str):
        subprocess.run(["say", text], check=False)


class TTSEngine:
    def __init__(self, desktop_requirements_dir: Optional[Path], spoken_log_file: Optional[Path] = None):
        self.desktop_requirements_dir = desktop_requirements_dir
        self.spoken_log_file = spoken_log_file

        self._q: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self.backend = self._detect_backend()

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _add_desktop_requirements_to_path(self):
        if not self.desktop_requirements_dir or not self.desktop_requirements_dir.exists():
            return

        if str(self.desktop_requirements_dir) not in sys.path:
            sys.path.insert(0, str(self.desktop_requirements_dir))

        deps_dir = self.desktop_requirements_dir / "deps"
        if deps_dir.exists():
            for wheel in deps_dir.glob("*.whl"):
                wheel_path = str(wheel)
                if wheel_path not in sys.path:
                    sys.path.append(wheel_path)

    def _detect_backend(self) -> TTSBackend:
        self._add_desktop_requirements_to_path()

        try:
            return CoquiBackend()
        except Exception:
            pass

        try:
            return Pyttsx3Backend()
        except Exception:
            pass

        return MacSayBackend()

    def _log_spoken_text(self, text: str):
        if not self.spoken_log_file:
            return
        self.spoken_log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.spoken_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {text}\\n")

    def _worker(self):
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.2)
            except queue.Empty:
                continue

            if text:
                self.backend.speak(text)
                self._log_spoken_text(text)

    def speak_async(self, text: str):
        clean = " ".join(text.split()).strip()
        if clean:
            self._q.put(clean)

    def shutdown(self):
        self._stop.set()
