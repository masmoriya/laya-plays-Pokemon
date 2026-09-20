"""Environment-driven provider selection."""

import os

from .providers import FakeProvider, JevProvider, LunaCodexProvider


def provider_from_env(name=None):
    name = (name or os.environ.get("AGENT_PROVIDER", "fake")).lower()
    if name == "luna_codex":
        return LunaCodexProvider()
    if name == "jev":
        return JevProvider()
    if name == "fake":
        return FakeProvider()
    raise ValueError(f"unknown AGENT_PROVIDER: {name}")

