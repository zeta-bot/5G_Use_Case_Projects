from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Deque, Dict, Optional


@dataclass
class BufferEvent:
    committed: str = ""
    cleared: bool = False
    deleted: bool = False
    speak_requested: bool = False


class SentenceBuffer:
    def __init__(
        self,
        stable_frames: int = 8,
        cooldown_frames: int = 6,
        mode: str = "word",
        word_map: Dict[str, str] | None = None,
        word_map_path: Optional[Path] = None,
    ):
        self.sentence = ""
        self.mode = mode
        self.stable_frames = stable_frames
        self.cooldown_frames = cooldown_frames
        # Stack of committed suffixes appended to `sentence`. Used for reliable undo/delete.
        self._commit_stack: list[str] = []

        default_word_map = {
            "HELLO": "hello",
            "YES": "yes",
            "NO": "no",
            "THANKS": "thanks",
            "PLEASE": "please",
            "SORRY": "sorry",
            "HELP": "help",
            "I": "I",
            "YOU": "you",
            "WE": "we",
            "GO": "go",
            "STOP": "stop",
            "WATER": "water",
            "FOOD": "food",
            "LOVE": "love",
            "WANT": "want",
            "NEED": "need",
            "I_NEED_WATER": "I need water",
            "I_NEED_FOOD": "I need food",
        }
        self.word_map = word_map or default_word_map
        if word_map_path:
            self.word_map = self._load_word_map(word_map_path, self.word_map)

        self.history: Deque[str] = deque(maxlen=stable_frames)
        self.cooldown = 0
        self.last_committed_label = ""

    @staticmethod
    def _load_word_map(path: Path, base_map: Dict[str, str]) -> Dict[str, str]:
        if not path.exists():
            return base_map
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(base_map)
            for k, v in raw.items():
                merged[str(k).strip().upper()] = str(v).strip()
            return merged
        except Exception:
            return base_map

    def set_mode(self, mode: str) -> None:
        if mode in {"word", "char"}:
            self.mode = mode

    def clear(self) -> None:
        self.sentence = ""
        self._commit_stack.clear()
        self.history.clear()
        self.cooldown = 0
        self.last_committed_label = ""

    def delete_last(self) -> None:
        """Delete the last committed segment (preferred) or last character as fallback."""
        if self._commit_stack:
            last = self._commit_stack[-1]
            if last and self.sentence.endswith(last):
                self.sentence = self.sentence[: -len(last)]
                self._commit_stack.pop()
                return
        self.sentence = self.sentence[:-1] if self.sentence else ""

    def _is_stable(self, label: str) -> bool:
        if len(self.history) < self.stable_frames:
            return False
        return all(item == label for item in self.history)

    def _append_token(self, token: str) -> str:
        if not token:
            return ""
        if self.mode == "word":
            sep = "" if (not self.sentence or self.sentence.endswith(" ")) else " "
            self.sentence += f"{sep}{token}"
            return f"{sep}{token}"

        self.sentence += token
        return token

    def _label_to_token(self, label: str) -> str:
        key = label.strip().upper()
        if key in {"SPACE", "DELETE", "CLEAR", "SPEAK"}:
            return ""
        if key in self.word_map:
            return self.word_map[key]

        # Generic fallback for trained models:
        # HELLO -> hello, I_NEED_WATER -> i need water
        token = key.replace("_", " ").lower()
        if token == "i":
            return "I"
        if token.startswith("i "):
            return "I " + token[2:]
        return token

    def update(self, label: str) -> BufferEvent:
        event = BufferEvent()
        self.history.append(label)

        if self.cooldown > 0:
            self.cooldown -= 1
            return event

        if not label or not self._is_stable(label):
            return event

        if label == self.last_committed_label:
            return event

        if label == "SPACE":
            if self.sentence and not self.sentence.endswith(" "):
                self.sentence += " "
                event.committed = " "
                self._commit_stack.append(" ")
        elif label == "DELETE":
            self.delete_last()
            event.deleted = True
        elif label == "CLEAR":
            self.sentence = ""
            self._commit_stack.clear()
            event.cleared = True
        elif label == "SPEAK":
            event.speak_requested = True
        else:
            token = self._label_to_token(label) if self.mode == "word" else label[:1].upper()
            event.committed = self._append_token(token)
            if event.committed:
                self._commit_stack.append(event.committed)

        self.last_committed_label = label
        self.cooldown = self.cooldown_frames
        return event
