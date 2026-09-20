"""Capture visible Gold 97 terrain and moving sprites as separate layers."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OverworldSprite:
    """One map-anchored overworld sprite."""

    key: str
    map_key: str
    pixel_x: int
    pixel_y: int
    rgba: bytes
    parts: int = 4


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

    def position(self, emulator, state):
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
        else:
            old_x, old_y = self.scroll
            self.origin = (self.origin[0] + (scroll_x - old_x + 128) % 256 - 128,
                           self.origin[1] + (scroll_y - old_y + 128) % 256 - 128)
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


def _sprite_cells(memory):
    blocked = set()
    for index in range(40):
        base = 0xFE00 + index * 4
        x, y = memory[base + 1] - 8, memory[base] - 16
        if x <= -8 or x >= 160 or y <= -8 or y >= 144:
            continue
        for row in range(max(0, y // 8), min(18, (y + 7) // 8 + 1)):
            for col in range(max(0, x // 8), min(20, (x + 7) // 8 + 1)):
                blocked.add((col, row))
    return blocked


def _tile_attr(memory, tilemap, tile_x, tile_y):
    try:
        return memory[1, tilemap.map_offset + tile_y * 32 + tile_x]
    except (AttributeError, TypeError):
        return 0


def visible_background(emulator, state, *, world_origin=None):
    """Return visible terrain, including the background beneath sprites."""
    view = _overworld_view(emulator, state)
    if view is None:
        return ()
    scroll_x, scroll_y, frame, (left, top) = view
    if world_origin is not None:
        left, top = world_origin[0] // 8, world_origin[1] // 8
    blocked = _sprite_cells(emulator.memory)
    tilemap = emulator.tilemap_background
    samples = []
    donors = {}
    for row in range(18):
        for col in range(20):
            world_x, world_y = left + col, top + row
            if not (0 <= world_x < state.map_width * 2
                    and 0 <= world_y < state.map_height * 2):
                continue
            tile_x, tile_y = (scroll_x // 8 + col) % 32, (scroll_y // 8 + row) % 32
            tile_id = tilemap.tile_identifier(tile_x, tile_y)
            attr = _tile_attr(emulator.memory, tilemap, tile_x, tile_y)
            covered = (col, row) in blocked
            pixels = None if covered else frame[row * 8:row * 8 + 8, col * 8:col * 8 + 8, :4].copy().tobytes()
            if pixels is not None:
                donors.setdefault((tile_id, attr), pixels)
            samples.append((world_x, world_y, tile_id, attr, tile_x, tile_y, pixels))
    palettes = {}
    result = []
    for world_x, world_y, tile_id, attr, tile_x, tile_y, pixels in samples:
        if pixels is None:
            pixels = donors.get((tile_id, attr))
            if pixels is None:
                raw = tilemap.tile(tile_x, tile_y).ndarray()
                palette = palettes.get(attr)
                if palette is None:
                    palette = _observed_palette(samples, tilemap, attr)
                    palettes[attr] = palette
                pixels = _recolor_tile(raw, palette)
        result.append((world_x, world_y, tile_id, pixels))
    return result


def _observed_palette(samples, tilemap, attr):
    palette = {}
    for _, _, _, sample_attr, tile_x, tile_y, pixels in samples:
        if sample_attr != attr or pixels is None:
            continue
        raw = tilemap.tile(tile_x, tile_y).ndarray().reshape(-1, 4)
        rendered = np.frombuffer(pixels, dtype=np.uint8).reshape(-1, 4)
        for source, color in zip(raw, rendered):
            palette[bytes(source)] = bytes(color)
        if len(palette) >= 4:
            break
    return palette


def _recolor_tile(raw, palette):
    return b"".join(palette.get(bytes(color), bytes(color)) for color in raw.reshape(-1, 4))


def _vram(memory, bank, address):
    if bank:
        try:
            return memory[bank, address]
        except TypeError:
            pass
    return memory[address]


def visible_entities(emulator, state, *, world_origin=None):
    """Return 16x16 NPC images from visible OAM pieces."""
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
