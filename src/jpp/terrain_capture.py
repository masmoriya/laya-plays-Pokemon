"""Capture visible Gold 97 terrain and moving sprites as separate layers."""

import numpy as np


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


def _overworld_view(emulator, state):
    if (getattr(state, "in_battle", False) or not getattr(state, "map_width", 0)
            or state.x is None or state.y is None):
        return None
    memory = emulator.memory
    if not memory[0xC2CE]:  # overworld sprite updates disabled in menus
        return None
    (scroll_x, scroll_y), (window_x, window_y) = emulator.screen.get_tilemap_position()
    if window_x < 160 and window_y < 144 or scroll_x % 8 or scroll_y % 8:
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


def visible_background(emulator, state):
    """Return only the 8x8 terrain cells visible this overworld frame."""
    view = _overworld_view(emulator, state)
    if view is None:
        return ()
    scroll_x, scroll_y, frame, (left, top) = view
    blocked = _sprite_cells(emulator.memory)
    tilemap = emulator.tilemap_background
    result = []
    for row in range(18):
        for col in range(20):
            if (col, row) in blocked:
                continue
            world_x, world_y = left + col, top + row
            if not (0 <= world_x < state.map_width * 2
                    and 0 <= world_y < state.map_height * 2):
                continue
            tile_x, tile_y = (scroll_x // 8 + col) % 32, (scroll_y // 8 + row) % 32
            pixels = frame[row * 8:row * 8 + 8, col * 8:col * 8 + 8, :4].copy().tobytes()
            result.append((world_x, world_y, tilemap.tile_identifier(tile_x, tile_y), pixels))
    return result


def _vram(memory, bank, address):
    if bank:
        try:
            return memory[bank, address]
        except TypeError:
            pass
    return memory[address]


def visible_entities(emulator, state):
    """Return on-screen NPC OAM graphics, never adding them to saved terrain."""
    view = _overworld_view(emulator, state)
    if view is None:
        return ()
    _, _, frame, (left, top) = view
    memory = emulator.memory
    entities = []
    for index in range(4, 40):  # OAM 0-3 is the player, marked separately
        base = 0xFE00 + index * 4
        sx, sy = memory[base + 1] - 8, memory[base] - 16
        if not (0 <= sx <= 152 and 0 <= sy <= 136):
            continue
        tile, attr = memory[base + 2], memory[base + 3]
        bank = 1 if attr & 0x08 else 0
        image = np.zeros((8, 8, 4), dtype=np.uint8)
        for row in range(8):
            source_row = 7 - row if attr & 0x40 else row
            address = 0x8000 + tile * 16 + source_row * 2
            low, high = _vram(memory, bank, address), _vram(memory, bank, address + 1)
            for col in range(8):
                source_col = col if attr & 0x20 else 7 - col
                if ((low >> source_col) & 1) | ((high >> source_col) & 1):
                    image[row, col] = frame[sy + row, sx + col]
        if image[:, :, 3].any():
            entities.append((left * 8 + sx, top * 8 + sy, image.tobytes()))
    return tuple(entities)


def visible_player(emulator, state):
    """Capture the chosen character's current 16x16 overworld frame from OAM/VRAM."""
    view = _overworld_view(emulator, state)
    if view is None:
        return None
    frame = view[2]
    memory = emulator.memory
    if _player_origin(memory, state) is None:
        return None
    positions = [(memory[0xFE01 + 4 * index] - 8,
                  memory[0xFE00 + 4 * index] - 16) for index in range(4)]
    left = min(x for x, _ in positions)
    top = min(y for _, y in positions)
    if not (0 <= left <= 144 and 0 <= top <= 128):
        return None
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    for index, (sx, sy) in enumerate(positions):
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
    return image.tobytes() if image[:, :, 3].any() else None
