"""Game adapter boundary. Unsupported ROMs get safe generic frame/control support."""

from dataclasses import dataclass
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Protocol

from .decode import decode
from .gold97_adapter import Gold97Adapter
from .progress.badge_tracker import BadgeTracker


@dataclass(frozen=True)
class LiveSnapshot:
    state: object
    badge_update: object | None
    title: str
    supports_ram_progress: bool


class GameAdapter(Protocol):
    title: str
    supports_ram_progress: bool

    def snapshot(self, emulator) -> LiveSnapshot: ...


class RedAdapter:
    supports_ram_progress = True

    def __init__(self, title="POKÉMON RED"):
        self.title = title
        self.badges = BadgeTracker()

    def snapshot(self, emulator):
        state = decode(emulator.memory)
        return LiveSnapshot(state, self.badges.update(emulator.memory), self.title, True)


class GenericAdapter:
    supports_ram_progress = False

    def __init__(self, title="GBC GAME"):
        self.title = title
        self.state = SimpleNamespace(map_name=title, in_battle=False, party=())

    def snapshot(self, emulator):
        # Do not reinterpret Gen 2 RAM as Gen 1 fields. Controls and frame output remain
        # fully usable; progress fields stay explicitly unavailable instead of lying.
        return LiveSnapshot(self.state, None, self.title, False)


ADAPTER_REGISTRY = {}


def register_adapter(cartridge_title, factory):
    """Register a game adapter without changing launcher logic."""
    ADAPTER_REGISTRY[str(cartridge_title).upper()] = factory


def _display_title(path, cartridge_title=None):
    title = str(cartridge_title or "").strip()
    if title and title not in {"PM_GOLD", "POKEMON RED", "POKEMON BLUE"}:
        return title[:24]
    stem = Path(path).stem.replace("_", " ").replace("-", " ")
    display = re.sub(r"\s+", " ", stem).strip().upper()
    if "GOLD" in display and "REFORGED" in display:
        return "GOLD REFORGED"
    return display[:24] or "GBC GAME"


def adapter_for_rom(path: str | Path, cartridge_title=None, forced="auto"):
    """Select decoder by cartridge identity; filename is only fallback display text."""
    title = str(cartridge_title or "").upper()
    if forced == "red" or title in {"POKEMON RED", "POKEMON BLUE"}:
        return RedAdapter("POKÉMON BLUE" if title == "POKEMON BLUE" else "POKÉMON RED")
    if forced == "gold97":
        return Gold97Adapter(path)
    if forced == "auto" and title == "PM_GOLD":
        try:
            return Gold97Adapter(path)
        except (OSError, ValueError):
            pass
    if forced == "auto" and title in ADAPTER_REGISTRY:
        return ADAPTER_REGISTRY[title](path)
    return GenericAdapter(_display_title(path, cartridge_title))


# Compatibility name for callers that used Gold-era MVP adapter directly.
GenericGBCAdapter = GenericAdapter
