"""Connect the desktop game to the shared local vision service before SDL starts."""

import os
import subprocess
import sys

from .laya_config import setting


def prepare_models(provider, vision=None):
    provider = (provider or os.environ.get("AGENT_PROVIDER") or "laya").lower()
    vision = vision or ("local" if provider == "laya" else "codex")
    os.environ["JPP_LOCAL_VLM"] = "1" if vision == "local" else "0"
    os.environ["LAYA_VISION"] = "0" if vision == "off" else "1"
    if vision != "local":
        return provider
    try:
        from laya_runtime.client import ModelClient
    except ImportError as exc:
        raise RuntimeError(
            "Local vision requires laya-runtime in this Jev environment. "
            "Install the local runtime package, or choose --vision codex / --vision off."
        ) from exc
    client = ModelClient()
    print(f"Connecting local vision: {client.model} at {client.base_url}", flush=True)
    try:
        client.health()
    except Exception:
        python = setting("vlm_python", sys.executable)
        print("Starting the local vision server…", flush=True)
        try:
            subprocess.run(
                [python, "-c", "from laya_runtime.server import ensure; ensure()"],
                check=True, timeout=150,
            )
            client.health()
        except Exception as exc:
            raise RuntimeError(
                "Local vision could not start. Check LAYA_VLM_PYTHON and the "
                "runtime server log; no cloud fallback was selected."
            ) from exc
    print("Local vision ready. F2 pauses/resumes play.", flush=True)
    return provider


def startup_requested(provider, restored_requested, autoplay=None):
    """An explicit CLI choice wins over a paused checkpoint."""
    if autoplay is not None:
        return autoplay
    return provider == "laya" or restored_requested
