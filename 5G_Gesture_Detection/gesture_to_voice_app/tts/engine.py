from __future__ import annotations

import json
import queue
import sys
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class Voice:
    id: str
    name: str


class BaseBackend:
    name = "base"

    def list_voices(self) -> List[Voice]:
        return []

    def set_voice(self, voice_id: str) -> None:
        _ = voice_id

    def speak(self, text: str) -> None:
        raise NotImplementedError


class KokoroBackend(BaseBackend):
    name = "kokoro"

    def __init__(self):
        from kokoro import KPipeline  # type: ignore
        import numpy as np
        import sounddevice as sd

        self._np = np
        self._sd = sd
        self._pipeline = KPipeline(lang_code="a")
        self._voice = "af_heart"

    def list_voices(self) -> List[Voice]:
        return [Voice(id="af_heart", name="af_heart")]

    def set_voice(self, voice_id: str) -> None:
        self._voice = voice_id

    def speak(self, text: str) -> None:
        generator = self._pipeline(text, voice=self._voice)
        chunks: list = []
        for _, _, audio in generator:
            arr = self._np.asarray(audio, dtype=self._np.float32).reshape(-1)
            if arr.size:
                chunks.append(arr)
        if not chunks:
            return
        merged = self._np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        self._sd.play(merged, samplerate=24000)
        self._sd.wait()


class CoquiBackend(BaseBackend):
    name = "coqui"

    def __init__(self):
        from TTS.api import TTS  # type: ignore
        import numpy as np
        import sounddevice as sd

        self._np = np
        self._sd = sd
        self._tts = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False)

    def speak(self, text: str) -> None:
        wav = self._tts.tts(text=text)
        sample_rate = 22050
        if hasattr(self._tts, "synthesizer") and hasattr(self._tts.synthesizer, "output_sample_rate"):
            sample_rate = int(self._tts.synthesizer.output_sample_rate)
        self._sd.play(self._np.array(wav, dtype=self._np.float32), samplerate=sample_rate)
        self._sd.wait()


class Pyttsx3Backend(BaseBackend):
    name = "pyttsx3"

    def __init__(self):
        import pyttsx3

        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", 160)

    def list_voices(self) -> List[Voice]:
        out: List[Voice] = []
        for voice in self._engine.getProperty("voices"):
            out.append(Voice(id=str(voice.id), name=str(getattr(voice, "name", voice.id))))
        return out

    def set_voice(self, voice_id: str) -> None:
        self._engine.setProperty("voice", voice_id)

    @staticmethod
    def _speak_in_subprocess(text: str, rate: int, voice_id: Optional[str]) -> None:
        """pyttsx3/NSSpeechSynthesizer often fails or skips audio off the main thread; one process per utterance is stable."""
        payload = json.dumps({"text": text, "rate": rate, "voice": voice_id})
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys; import pyttsx3; "
                "p=json.loads(sys.argv[1]); "
                "e=pyttsx3.init(); "
                "e.setProperty('rate', int(p.get('rate', 160))); "
                "v=p.get('voice'); "
                "e.setProperty('voice', v) if v else None; "
                "e.say(p['text']); e.runAndWait()",
                payload,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"pyttsx3 subprocess failed (code {proc.returncode}): {err or 'no stderr'}")

    def speak(self, text: str) -> None:
        try:
            rate = int(self._engine.getProperty("rate"))
        except Exception:
            rate = 160
        try:
            voice_id = self._engine.getProperty("voice")
        except Exception:
            voice_id = None
        voice_str = str(voice_id) if voice_id is not None else None

        if threading.current_thread() is threading.main_thread():
            self._engine.say(text)
            self._engine.runAndWait()
        else:
            self._speak_in_subprocess(text, rate, voice_str)


class MacSayBackend(BaseBackend):
    name = "macos-say"

    def list_voices(self) -> List[Voice]:
        return []

    def speak(self, text: str) -> None:
        subprocess.run(["say", text], check=False)


class TTSEngine:
    def __init__(
        self,
        voice_id: Optional[str] = None,
        spoken_log_file: Optional[Path] = None,
        preferred_backend: str = "auto",
        strict_preferred: bool = False,
    ):
        # Unbounded queue: bounded queue + put_nowait dropped utterances silently (non-uniform TTS).
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._backend_lock = threading.RLock()
        self.spoken_log_file = spoken_log_file
        self._voice_id = voice_id
        self.preferred_backend = self._normalize_backend_name(preferred_backend)
        self.strict_preferred = strict_preferred

        self.backend = self._select_backend(self.preferred_backend, strict_preferred=self.strict_preferred)
        if self._voice_id:
            try:
                self.backend.set_voice(self._voice_id)
            except Exception:
                pass

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @staticmethod
    def _normalize_backend_name(name: str) -> str:
        raw = (name or "auto").strip().lower()
        aliases = {
            "kokuro": "kokoro",  # Common spelling variant.
        }
        return aliases.get(raw, raw)

    def _select_backend(self, preferred_backend: str = "auto", strict_preferred: bool = False) -> BaseBackend:
        backend_map = {
            "kokoro": KokoroBackend,
            "coqui": CoquiBackend,
            "pyttsx3": Pyttsx3Backend,
            "say": MacSayBackend,
        }
        ordered = [KokoroBackend, CoquiBackend, Pyttsx3Backend, MacSayBackend]

        if preferred_backend != "auto":
            if preferred_backend not in backend_map:
                raise ValueError(
                    f"Unknown TTS backend '{preferred_backend}'. "
                    "Use one of: auto, kokoro, coqui, pyttsx3, say."
                )
            preferred_cls = backend_map[preferred_backend]
            try:
                return preferred_cls()
            except Exception as exc:
                if strict_preferred:
                    raise RuntimeError(
                        f"Requested TTS backend '{preferred_backend}' is unavailable: {exc}"
                    ) from exc
                ordered = [c for c in ordered if c is not preferred_cls]

        for backend_cls in ordered:
            try:
                return backend_cls()
            except Exception:
                continue
        raise RuntimeError("No TTS backend could be initialized.")

    def list_voices(self) -> List[Voice]:
        with self._backend_lock:
            try:
                return self.backend.list_voices()
            except Exception:
                return []

    def set_backend(self, backend_name: str, strict_preferred: bool = True) -> bool:
        normalized = self._normalize_backend_name(backend_name)
        try:
            new_backend = self._select_backend(normalized, strict_preferred=strict_preferred)
        except Exception:
            return False

        with self._backend_lock:
            self.backend = new_backend
            self.preferred_backend = normalized
            self.strict_preferred = strict_preferred
            if self._voice_id:
                try:
                    self.backend.set_voice(self._voice_id)
                except Exception:
                    pass
        return True

    def toggle_between(self, primary_backend: str = "kokoro", fallback_backend: str = "pyttsx3") -> str:
        primary = self._normalize_backend_name(primary_backend)
        fallback = self._normalize_backend_name(fallback_backend)

        with self._backend_lock:
            current = self.backend.name

        target = fallback if current == primary else primary
        if self.set_backend(target, strict_preferred=False):
            with self._backend_lock:
                return self.backend.name

        # If switching to target fails, try fallback as a safe endpoint.
        if self.set_backend(fallback, strict_preferred=False):
            with self._backend_lock:
                return self.backend.name

        with self._backend_lock:
            return self.backend.name

    def _log(self, text: str) -> None:
        if not self.spoken_log_file:
            return
        self.spoken_log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.spoken_log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")

    def speak(self, text: str) -> None:
        clean = " ".join(text.split()).strip()
        if not clean:
            return
        with self._backend_lock:
            active_backend = self.backend
            strict_preferred = self.strict_preferred
            preferred_backend = self.preferred_backend
        try:
            active_backend.speak(clean)
            self._log(clean)
            return
        except Exception as exc:
            if strict_preferred and preferred_backend != "auto":
                raise RuntimeError(
                    f"[TTS] Required backend '{preferred_backend}' failed during synthesis: {exc}"
                ) from exc
            print(
                f"[TTS] Backend '{active_backend.name}' failed: {exc}. Falling back to macos-say.",
                file=sys.stderr,
            )

        # Runtime safety fallback so speaking never fails silently.
        with self._backend_lock:
            self.backend = MacSayBackend()
            self.preferred_backend = "say"
            self.strict_preferred = False
            active_backend = self.backend
        active_backend.speak(clean)
        self._log(clean)

    def speak_async(self, text: str) -> None:
        clean = " ".join(text.split()).strip()
        if not clean:
            return
        self._queue.put(clean)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.speak(text)
            except Exception as exc:
                print(f"[TTS] Failed to speak text: {exc}", file=sys.stderr)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
