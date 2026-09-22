"""Rotating PyBoy save-state checkpoints; files stay ignored by git."""

import os
import re
import tempfile
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
        # PyBoy writes a large binary stream.  Write beside the final path and
        # publish it only after the stream is complete so an interrupted exit
        # cannot become the newest (but unreadable) checkpoint.
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{path.name}.", dir=self.directory, delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                emulator.save_state(handle)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        os.replace(temporary_path, path)
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
        states = self.candidates(run_id)
        return states[0] if states else None

    def candidates(self, run_id=None):
        """Return possible checkpoints newest first, including legacy names."""
        states = list(self.directory.glob("*.state"))
        if run_id is not None:
            prefix = f"{_safe_component(run_id)}-"
            states = [item for item in states if item.name.startswith(prefix)]
            if not states:
                # Checkpoints written before run-scoped filenames existed are
                # safe to reuse only when they match that legacy shape.
                states = [
                    item for item in self.directory.glob("*.state")
                    if re.match(r"^\d{8}T\d{6}Z-", item.name)
                ]
        return sorted(states, key=lambda item: item.stat().st_mtime, reverse=True)

    def latest_reason(self, run_id, reason):
        """Find a protected recovery point without selecting the stuck exit save."""
        prefix = f"{_safe_component(run_id)}-"
        suffix = f"-{_safe_component(reason)}.state"
        states = sorted(
            (item for item in self.directory.glob("*.state")
             if item.name.startswith(prefix) and item.name.endswith(suffix)),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        return states[0] if states else None


def _safe_component(value):
    """Keep checkpoint names predictable even when run IDs are user supplied."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip(".-")
    return value or "run"
