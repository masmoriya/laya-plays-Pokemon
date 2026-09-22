"""A paused-clock visual loop: decisions only act on the exact observed screen."""

import time
import threading
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from laya_runtime.config import atomic_json
from laya_runtime.contracts import BUTTONS
from laya_runtime.game_provider import VisualProvider, frame_id, scene_id
from laya_runtime.journal import Commands, Journal
from PIL import Image

from .visual_checkpoints import VisualCheckpoints, release


class VisualLoop:
    def __init__(self, emulator, session, directory, adapter=None):
        self.emulator, self.session, self.directory = emulator, session, directory
        self.work = Path(session["work"])
        self.adapter = adapter
        self.journal = Journal(self.work)
        self.commands = Commands(directory)
        self.checkpoints = VisualCheckpoints(emulator, self.work)
        self.provider = VisualProvider()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.cancel = threading.Event()
        self.future_generation = 0
        self.generation = 0
        self.playing = True
        self.stopping = False
        self.count = self.rewinds = 0
        self.recent = deque(maxlen=20)
        self.world = {"objective": session["goal"]}
        self.previous = None
        self.pending_checkpoint = None
        self.experiment_checkpoint = None
        self.status = "starting"
        latest = self.work / "resume.state"
        initial = session.get("initial_state")
        if latest.exists() or initial:
            self.world = {**self.world, **self.checkpoints.restore(latest if latest.exists() else initial)}
            self.world["objective"] = session["goal"]
        else:
            emulator.tick(60, True)
        self.publish("ready")

    def image(self):
        return Image.fromarray(self.emulator.screen.ndarray[:, :, :3].copy())

    def publish(self, status, detail="", **extra):
        self.status = status
        image = self.image()
        temporary = self.directory / "frame.tmp.png"
        image.save(temporary)
        temporary.replace(self.directory / "frame.png")
        atomic_json(self.directory / "status.json", {
            "status": status, "detail": detail, "decisions": self.count,
            "rewinds": self.rewinds, "generation": self.generation,
            "frame_id": frame_id(image), "objective": self.world.get("objective"),
            "mode": "visual", "updated": time.time(), **extra})

    def command(self, action):
        self.generation += 1
        self.cancel.set()
        release(self.emulator)
        if action == "play":
            self.playing = True
        elif action == "pause":
            self.playing = False
        elif action == "stop":
            self.stopping = True
            self.playing = False
        elif action == "rewind":
            self.playing = False
            self.world = self.checkpoints.rewind()
            self.previous = None
            self.pending_checkpoint = None
            self.experiment_checkpoint = None
            self.publish("paused", "Restored an earlier experiment")
            return
        elif action in BUTTONS:
            self.playing = False
            self.checkpoints.save(self.world, "manual-input")
            if action != "wait":
                self.emulator.button(action, 4)
            self.emulator.tick(4, True)
            release(self.emulator)
            self.publish("paused", "Human control")
            return
        if not self.playing:
            self.publish("paused")

    def tick(self):
        for action in self.commands.pop():
            try:
                self.command(action)
            except ValueError as exc:
                self.publish("paused", str(exc))
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                if self.playing and self.future_generation == self.generation:
                    result = future.result()
                    self.accept(result)
            except Exception as exc:
                self.playing = False
                self.publish("blocked", str(exc)[:400])
        if self.playing and self.future is None and not self.stopping:
            image = self.image()
            self.request = {"goal": self.world["objective"],
                            "memory": self.journal.context(scene_id(image))}
            if self.adapter and self.adapter.supports_ram_progress:
                from .visual_state import adapter_facts
                self.request["memory"]["adapter"] = adapter_facts(self.adapter, self.emulator)
            self.cancel = threading.Event()
            self.future_generation = self.generation
            self.future = self.executor.submit(self.provider.decide, image,
                previous=self.previous, generation=self.generation, cancel=self.cancel, **self.request)
            self.publish("thinking")

    def accept(self, result):
        image = self.image()
        step = self.provider.validate_current(result, image, self.generation)
        if step.observation.setback and step.observation.evidence and self.pending_checkpoint:
            self._rewind("Visible setback: " + step.observation.evidence)
            return
        checkpoint = self.checkpoints.save(self.world)
        self.pending_checkpoint = checkpoint
        if self.experiment_checkpoint is None or not self.experiment_checkpoint.exists():
            self.experiment_checkpoint = checkpoint
        frames = self.work / "frames"
        frames.mkdir(exist_ok=True)
        before = frame_id(image)
        image.save(frames / f"{before}.png")
        if self.previous:
            self.previous.save(frames / f"{frame_id(self.previous)}.png")
        for action in step.actions:
            if action.button != "wait":
                self.emulator.button(action.button, action.frames)
            self.emulator.tick(action.frames, True)
            release(self.emulator)
        after_image = self.image()
        after = frame_id(after_image)
        after_image.save(frames / f"{after}.png")
        outcome = {"executed": True, "before": before, "after": after,
                   "changed": before != after, "checkpoint": str(checkpoint),
                   "previous": frame_id(self.previous) if self.previous else None,
                   "model": result["model"], "usage": result["usage"]}
        self.journal.record(self.session["id"], scene_id(image), self.request,
                            step.model_dump(), outcome)
        self.count += 1
        self.recent.append(scene_id(after_image))
        self.previous = image
        self.world.update(last_observation=step.observation.model_dump())
        # A requested user objective remains authoritative, including across restarts.
        repeated = Counter(self.recent)[scene_id(after_image)]
        if repeated >= 8:
            self.pending_checkpoint = self.experiment_checkpoint
            self._rewind("Repeated scene without observed progress")
        else:
            if repeated == 1:
                self.experiment_checkpoint = checkpoint
            self.publish("playing", step.expected, observation=step.observation.model_dump())

    def _rewind(self, reason):
        self.journal.record(self.session["id"], scene_id(self.image()), {}, {},
                            {"rewound": True, "reason": reason, "executed": False})
        self.world = self.checkpoints.restore(self.pending_checkpoint)
        self.pending_checkpoint = None
        self.experiment_checkpoint = None
        self.world.setdefault("objective", self.session["goal"])
        self.previous = None
        self.recent.clear()
        self.generation += 1
        self.rewinds += 1
        if self.rewinds >= 3:
            self.playing = False
            self.publish("blocked", "Three unsuccessful experiments. Add a note or take control.")
        else:
            self.publish("playing", reason + "; experiment rewound")

    def close(self):
        self.generation += 1
        self.cancel.set()
        self.playing = False
        release(self.emulator)
        self.checkpoints.save(self.world, "exit")
        latest = self.work / "resume.state"
        temporary = self.work / "resume.tmp.state"
        with temporary.open("wb") as handle:
            self.emulator.save_state(handle)
        temporary.replace(latest)
        atomic_json(latest.with_suffix(".json"), self.world)
        self.publish("stopped")
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.commands.close()
        self.journal.close()
