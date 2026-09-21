"""Capture visible Gold 97 terrain and moving sprites as separate layers."""

from dataclasses import dataclass, replace

import numpy as np

from .terrain_tiles import background_tiles


# Gold 97 keeps Crystal's map-object layout and shifts this WRAMX block by the
# five bytes inserted before the map/party data. The map object stores object
# type and sprite separately, so item balls can be identified without guessing
# from rendered pixels.
_GOLD97_MAP_OBJECTS = 0xD723
_MAP_OBJECT_LENGTH = 16
_MAP_OBJECT_SPRITE = 1
_MAP_OBJECT_Y = 2
_MAP_OBJECT_X = 3
_MAP_OBJECT_TYPE = 8
_MAP_OBJECT_STRUCT_ID = 0
_OBJECTTYPE_ITEMBALL = 1
_SPRITE_POKE_BALL = 0x54


@dataclass(frozen=True)
class OverworldSprite:
    """One map-anchored overworld sprite."""

    key: str
    map_key: str
    pixel_x: int
    pixel_y: int
    rgba: bytes
    parts: int = 4
    # Object classification is optional: the capture layer cannot safely infer
    # NPC versus item from pixels alone, but ROM-aware callers can provide it.
    kind: str = "unknown"


def _map_key(state):
    return f"{getattr(state, 'map_group', 0):02X}:{getattr(state, 'map_number', 0):02X}"


class WorldCamera:
    """Keep the screen-to-map offset steady while the camera scrolls."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.map_key = None
        self.scroll = None
        self.origin = None
        self.map_frames = 0

    def position(self, emulator, state):
        if getattr(state, "in_battle", False):
            self.reset()
            return None
        view = _overworld_view(emulator, state, aligned=False)
        if view is None:
            return None
        scroll_x, scroll_y = view[:2]
        map_key = _map_key(state)
        if self.map_key != map_key:
            if scroll_x % 8 or scroll_y % 8:
                return None
            self.origin = (view[3][0] * 8, view[3][1] * 8)
            self.map_key = map_key
            self.map_frames = 1
        else:
            old_x, old_y = self.scroll
            self.origin = (self.origin[0] + (scroll_x - old_x + 128) % 256 - 128,
                           self.origin[1] + (scroll_y - old_y + 128) % 256 - 128)
            self.map_frames += 1
        self.scroll = (scroll_x, scroll_y)
        return self.origin


def _player_origin(memory, state):
    """Convert 16-pixel map steps to the viewport's 8-pixel tile grid."""
    positions = [(memory[0xFE01 + 4 * index] - 8,
                  memory[0xFE00 + 4 * index] - 16) for index in range(4)]
    left = min(x for x, _ in positions)
    top = min(y for _, y in positions)
    if ({(x - left, y - top) for x, y in positions}
            != {(0, 0), (8, 0), (0, 8), (8, 8)}):
        return None
    # Facing/walking animation shifts the drawing by up to four pixels even
    # while the underlying map cell is stationary. Snap that graphic offset
    # back to its map anchor before locating the viewport.
    return (state.x * 2 - (left + 4) // 8,
            state.y * 2 - (top + 15) // 8)


def _overworld_view(emulator, state, *, aligned=True):
    if (getattr(state, "in_battle", False) or not getattr(state, "map_width", 0)
            or state.x is None or state.y is None):
        return None
    memory = emulator.memory
    if not memory[0xC2CE]:  # overworld sprite updates disabled in menus
        return None
    (scroll_x, scroll_y), (window_x, window_y) = emulator.screen.get_tilemap_position()
    if (window_x < 160 and window_y < 144 or
            (aligned and (scroll_x % 8 or scroll_y % 8))):
        return None
    frame = emulator.screen.ndarray
    white = (frame[:, :, :3] > 224).all(axis=2)
    if white.mean() > 0.30 or white[-40:].mean() > 0.55:
        return None
    origin = _player_origin(memory, state)
    return (scroll_x, scroll_y, frame, origin) if origin is not None else None


def overworld_ready(emulator, state):
    """Trust the rendered map, even when map tiles decode as stale text."""
    return _overworld_view(emulator, state, aligned=False) is not None


def visible_prompt(emulator, state):
    """Require a visible text box before confirming a non-battle screen."""
    lines = getattr(state, "screen_lines", ()) or ()
    has_text = any(line.strip() for line in lines[12:])
    has_cursor = (getattr(state, "screen_cursor", None) is not None and
                  any(line.strip() for line in lines))
    if not (has_text or has_cursor):
        return False
    frame = emulator.screen.ndarray
    white = (frame[:, :, :3] > 224).all(axis=2)
    return white[-40:].mean() > 0.55 and white.mean() < 0.65


def visible_background(emulator, state, *, world_origin=None):
    """Return the real background beneath sprites, never screen pixels."""
    view = _overworld_view(emulator, state)
    if view is None:
        return ()
    scroll_x, scroll_y, _, (left, top) = view
    if world_origin is not None:
        left, top = world_origin[0] // 8, world_origin[1] // 8
    return background_tiles(emulator, state, scroll_x, scroll_y, left, top)


def _vram(memory, bank, address):
    if bank:
        try:
            return memory[bank, address]
        except TypeError:
            pass
    return memory[address]


def _wram(memory, address):
    try:
        return memory[1, address]
    except TypeError:
        return memory[address]


def _visible_gold97_items(emulator, state):
    """Read active item-ball objects close enough to be on the visible map."""
    if not hasattr(state, "map_group") or state.x is None or state.y is None:
        return ()
    map_key = _map_key(state)
    items = []
    for index in range(1, 16):
        base = _GOLD97_MAP_OBJECTS + index * _MAP_OBJECT_LENGTH
        if (_wram(emulator.memory, base + _MAP_OBJECT_STRUCT_ID) == 0xFF or
                _wram(emulator.memory, base + _MAP_OBJECT_SPRITE) != _SPRITE_POKE_BALL or
                _wram(emulator.memory, base + _MAP_OBJECT_TYPE) & 0x0F != _OBJECTTYPE_ITEMBALL):
            continue
        x = _wram(emulator.memory, base + _MAP_OBJECT_X) - 4
        y = _wram(emulator.memory, base + _MAP_OBJECT_Y) - 4
        if (not 0 <= x < getattr(state, "map_width", 0) or
                not 0 <= y < getattr(state, "map_height", 0) or
                abs(x - state.x) > 10 or abs(y - state.y) > 9):
            continue
        items.append(OverworldSprite(
            key=f"item:{map_key}:{index}", map_key=map_key,
            pixel_x=x * 16, pixel_y=y * 16, rgba=bytes(1024), kind="item"))
    return tuple(items)


def visible_entities(emulator, state, *, world_origin=None):
    """Return visible NPC images and explicitly decoded item objects."""
    view = _overworld_view(emulator, state, aligned=False)
    if view is None:
        return ()
    _, _, frame, tile_origin = view
    memory = emulator.memory
    if world_origin is None:
        world_origin = tile_origin[0] * 8, tile_origin[1] * 8
    entities = []
    for slot in range(4, 40, 4):
        visible = [(index, memory[0xFE01 + 4 * index] - 8,
                    memory[0xFE00 + 4 * index] - 16) for index in range(slot, slot + 4)]
        visible = [(index, x, y) for index, x, y in visible
                   if 0 <= x <= 152 and 0 <= y <= 136]
        if len(visible) < 2:
            continue
        positions = [(x, y) for _, x, y in visible]
        sx, sy = min(x for x, _ in positions), min(y for _, y in positions)
        if not (0 <= sx <= 144 and 0 <= sy <= 128):
            continue
        offsets = {(x - sx, y - sy) for x, y in positions}
        if (len(offsets) != len(positions) or
                not offsets.issubset({(0, 0), (8, 0), (0, 8), (8, 8)})):
            continue
        image = _sprite_image(memory, frame, [index for index, _, _ in visible], positions, sx, sy)
        if image[:, :, 3].any():
            entities.append(OverworldSprite(
                key=f"oam:{slot}", map_key=_map_key(state),
                pixel_x=world_origin[0] + sx, pixel_y=world_origin[1] + sy,
                rgba=image.tobytes(), parts=len(visible),
            ))
    objects = getattr(state, 'overworld_objects', None)
    if objects is not None:
        canonical = []
        for identity, x, y in objects:
            nearby = min(entities, key=lambda e: abs(e.pixel_x-x*16)+abs(e.pixel_y-y*16), default=None)
            rgba = nearby.rgba if nearby and abs(nearby.pixel_x-x*16)+abs(nearby.pixel_y-y*16) <= 24 else bytes(1024)
            canonical.append(OverworldSprite(identity, _map_key(state), x*16, y*16, rgba, kind='npc'))
        entities = canonical
    items = _visible_gold97_items(emulator, state)
    item_cells = {(e.pixel_x, e.pixel_y) for e in items}
    entities = [e for e in entities if (e.pixel_x, e.pixel_y) not in item_cells]
    entities.extend(items)
    return tuple(entities)


def _sprite_image(memory, frame, indices, positions, left, top):
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    for index, (sx, sy) in zip(indices, positions):
        tile, attr = memory[0xFE02 + index * 4], memory[0xFE03 + index * 4]
        bank = 1 if attr & 0x08 else 0
        for row in range(8):
            source_row = 7 - row if attr & 0x40 else row
            address = 0x8000 + tile * 16 + source_row * 2
            low, high = _vram(memory, bank, address), _vram(memory, bank, address + 1)
            for col in range(8):
                bit = col if attr & 0x20 else 7 - col
                if (low >> bit & 1) | (high >> bit & 1):
                    image[sy - top + row, sx - left + col] = frame[sy + row, sx + col]
    return image


def visible_player(emulator, state, *, world_origin=None):
    """Capture the chosen character's current 16x16 overworld frame from OAM/VRAM."""
    view = _overworld_view(emulator, state, aligned=False)
    if view is None:
        return None
    _, _, frame, tile_origin = view
    memory = emulator.memory
    if _player_origin(memory, state) is None:
        return None
    positions = [(memory[0xFE01 + 4 * index] - 8,
                  memory[0xFE00 + 4 * index] - 16) for index in range(4)]
    left = min(x for x, _ in positions)
    top = min(y for _, y in positions)
    if not (0 <= left <= 144 and 0 <= top <= 128):
        return None
    image = _sprite_image(memory, frame, range(4), positions, left, top)
    if not image[:, :, 3].any():
        return None
    return OverworldSprite(
        key="player", map_key=_map_key(state),
        pixel_x=(world_origin[0] if world_origin else tile_origin[0] * 8) + left,
        pixel_y=(world_origin[1] if world_origin else tile_origin[1] * 8) + top,
        rgba=image.tobytes(),
    )
