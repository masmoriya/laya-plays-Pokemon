"""Rotating PyBoy save-state checkpoints; files stay ignored by git."""

import re
from datetime import datetime, timezone
from pathlib import Path


class CheckpointManager:
    def __init__(self, directory="data/checkpoints", keep=5):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.keep = keep

    def save(self, emulator, metadata, reason="interval"):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_id = _safe_component(metadata.get("run_id", "run"))
        path = self.directory / f"{run_id}-{stamp}-{_safe_component(reason)}.state"
        with path.open("wb") as handle:
            emulator.save_state(handle)
        protected = {"snapshot", "before-restart", "manual", "encounter"}
        states = sorted(
            (item for item in self.directory.glob(f"{run_id}-*.state")
             if not any(item.stem.endswith(f"-{kind}") for kind in protected)),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in states[self.keep :]:
            old.unlink(missing_ok=True)
        return path, {**metadata, "reason": reason, "path": str(path)}

    def latest(self, run_id=None):
        states = self.directory.glob("*.state")
        if run_id is not None:
            prefix = f"{_safe_component(run_id)}-"
            states = (item for item in states if item.name.startswith(prefix))
        states = sorted(states, key=lambda item: item.stat().st_mtime, reverse=True)
        if not states and run_id is not None:
            # Checkpoints written before run-scoped filenames existed are safe to
            # reuse only when they match that legacy timestamp-only shape.
            states = sorted(
                (
                    item
                    for item in self.directory.glob("*.state")
                    if re.match(r"^\d{8}T\d{6}Z-", item.name)
                ),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        return states[0] if states else None


def _safe_component(value):
    """Keep checkpoint names predictable even when run IDs are user supplied."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip(".-")
    return value or "run"
