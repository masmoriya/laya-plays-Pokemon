"""Health checks and bounded restart hooks for unattended process."""

from dataclasses import dataclass
import shutil
import time


@dataclass
class Health:
    emulator: bool
    frame_age: float
    checkpoint_age: float
    disk_free: int
    codex: bool = True
    ffmpeg: bool = True

    @property
    def healthy(self):
        return self.emulator and self.frame_age < 30 and self.checkpoint_age < 900 and self.disk_free > 256 * 1024 * 1024


class Watchdog:
    def __init__(self, checkpoint_path="data/checkpoints"):
        self.checkpoint_path = checkpoint_path
        self.last_frame = time.monotonic()
        self.last_checkpoint = time.monotonic()

    def frame_seen(self):
        self.last_frame = time.monotonic()

    def checkpoint_seen(self):
        self.last_checkpoint = time.monotonic()

    def check(self, emulator, codex=True, ffmpeg=True):
        free = shutil.disk_usage(".").free
        return Health(
            emulator=emulator is not None,
            frame_age=time.monotonic() - self.last_frame,
            checkpoint_age=time.monotonic() - self.last_checkpoint,
            disk_free=free,
            codex=codex,
            ffmpeg=ffmpeg,
        )

