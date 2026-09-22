"""Small launcher bridge for the existing Gold97 dashboard and controller."""

import os
import shutil
import time
from pathlib import Path

from laya_runtime.config import atomic_json, model_home
from laya_runtime.journal import Commands
from PIL import Image


class LiveBridge:
    def __init__(self, session, directory):
        self.session, self.directory = session, directory
        self.queue = Commands(directory)
        self.last_publish = 0
        self.rewind_point = None

    def commands(self):
        return self.queue.pop()

    def publish(self, emulator, controller, autonomous):
        if time.monotonic() - self.last_publish < .5:
            return
        self.last_publish = time.monotonic()
        image = Image.fromarray(emulator.screen.ndarray[:, :, :3].copy())
        temporary = self.directory / "frame.tmp.png"
        image.save(temporary)
        temporary.replace(self.directory / "frame.png")
        status = ("blocked" if controller and controller.paused else
                  "playing" if autonomous else "paused")
        atomic_json(self.directory / "status.json", {"status": status,
            "mode": "gold97", "objective": self.session["goal"],
            "detail": controller.pause_reason if controller else "",
            "updated": time.time(), "run_id": "managed"})


def run_gold97(session, directory):
    work = Path(session["work"])
    source = Path(__file__).resolve().parents[2] / "config"
    if not source.exists():
        source = Path(__file__).resolve().parent / "resources"
    if source.is_dir():
        shutil.copytree(source, work / "config", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.local.json"))
    os.environ["JPP_LOCAL_VLM"] = "1"
    os.environ.setdefault("LAYA_MODEL_PATH", str(model_home() / "multilingual"))
    if session["headless"]:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    previous = Path.cwd()
    os.chdir(work)
    bridge = LiveBridge(session, directory)
    try:
        from .live import run
        has_resume = bool(list((work / "data/checkpoints").glob("managed-*.state")))
        run(Path(session["rom"]), state=None if has_resume else session.get("initial_state"),
            run_id="managed", provider_name="laya", runtime_bridge=bridge)
    finally:
        os.chdir(previous)
        bridge.queue.close()
        atomic_json(directory / "status.json", {"status": "stopped", "mode": "gold97"})
