"""Bounded reversible experiments, retaining failure history outside checkpoints."""

import json
from pathlib import Path

from laya_runtime.config import atomic_json
from laya_runtime.contracts import BUTTONS

from .checkpoints import CheckpointManager


def release(emulator):
    for button in BUTTONS:
        if button != "wait":
            emulator.button_release(button)


class VisualCheckpoints:
    def __init__(self, emulator, work):
        self.emulator = emulator
        self.work = Path(work)
        self.manager = CheckpointManager(self.work / "checkpoints", keep=12)
        self.history = list(reversed(self.manager.candidates("visual")[:10]))

    def save(self, world, reason="experiment"):
        release(self.emulator)
        path, _ = self.manager.save(self.emulator, {"run_id": "visual"}, reason)
        atomic_json(path.with_suffix(".json"), world)
        for metadata in self.manager.directory.glob("visual-*.json"):
            if not metadata.with_suffix(".state").exists():
                metadata.unlink()
        self.history.append(path)
        self.history = self.history[-10:]
        return path

    def restore(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.work.resolve()):
            raise ValueError("Checkpoint is outside this save lineage")
        metadata = path.with_suffix(".json")
        world = json.loads(metadata.read_text()) if metadata.exists() else {}
        with path.open("rb") as handle:
            self.emulator.load_state(handle)
        release(self.emulator)
        return world

    def rewind(self):
        existing = [p for p in self.history if p.exists()]
        if not existing:
            raise ValueError("No earlier experiment checkpoint is available")
        path = existing.pop()
        self.history = existing
        return self.restore(path)
