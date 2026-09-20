"""Sprite-sheet animation timing. Rendering stays optional for headless play."""

from dataclasses import dataclass
import json
from pathlib import Path
import time

from .character_state import CharacterState, EVENT_STATES


DEFAULT_ANIMATIONS = {
    "idle": {"frames": 4, "fps": 3, "loop": True},
    "thinking": {"frames": 6, "fps": 6, "loop": True},
    "decided": {"frames": 2, "fps": 4, "loop": False},
    "battle": {"frames": 4, "fps": 6, "loop": True},
    "celebrate": {"frames": 8, "fps": 8, "loop": False},
    "confused": {"frames": 4, "fps": 4, "loop": True},
    "recovering": {"frames": 6, "fps": 8, "loop": True},
    "hurt": {"frames": 2, "fps": 5, "loop": False},
    "sleep": {"frames": 4, "fps": 2, "loop": True},
}


@dataclass
class Animation:
    state: CharacterState = CharacterState.IDLE
    started_at: float = 0.0
    config: dict | None = None

    def __post_init__(self):
        self.started_at = self.started_at or time.monotonic()
        self.config = self.config or DEFAULT_ANIMATIONS

    def handle_event(self, event_type):
        self.state = EVENT_STATES.get(str(event_type), self.state)
        self.started_at = time.monotonic()

    def frame(self, now=None):
        now = time.monotonic() if now is None else now
        spec = self.config[self.state.value]
        index = int(max(0.0, now - self.started_at) * spec["fps"])
        if spec["loop"]:
            return index % spec["frames"]
        return min(index, spec["frames"] - 1)

    @classmethod
    def from_file(cls, path):
        data = json.loads(Path(path).read_text())
        return cls(config={**DEFAULT_ANIMATIONS, **data})

