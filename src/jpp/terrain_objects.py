"""Exact-build visible object categories; no puzzle or location guidance."""

# Exact supported ROM: map-object records at D6FC, matched against active
# object IDs and real checkpoints. Sprite constants must be counted from const
# declarations: the upstream hexadecimal comments are stale (ball is 4E).
_GOLD97_MAP_OBJECTS = 0xD6FC
_MAP_OBJECT_LENGTH = 16
_MAP_OBJECT_SPRITE = 1
_MAP_OBJECT_Y = 2
_MAP_OBJECT_X = 3
_MAP_OBJECT_TYPE = 8
_MAP_OBJECT_STRUCT_ID = 0
_OBJECTTYPE_ITEMBALL = 1
_SPRITE_POKE_BALL = 0x4E


def _wram(memory, address):
    try:
        return memory[1, address]
    except TypeError:
        return memory[address]


def visible_items(emulator, state):
    """Read active item-ball objects close enough to be on the visible map."""
    if (not getattr(state, "mechanics_verified", False)
            or not hasattr(state, "map_group") or state.x is None or state.y is None):
        return ()
    from .terrain_capture import OverworldSprite
    map_key = f"{state.map_group:02X}:{state.map_number:02X}"
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
            key=f"object:{index}", map_key=map_key,
            pixel_x=x * 16, pixel_y=y * 16, rgba=bytes(1024), kind="item"))
    return tuple(items)


def object_kind(memory, state, identity):
    if getattr(state, 'mechanics_verified', False) and identity.startswith('object:'):
        index = int(identity.split(':')[1])
        base = _GOLD97_MAP_OBJECTS + index * _MAP_OBJECT_LENGTH
        sprite = _wram(memory, base + _MAP_OBJECT_SPRITE)
        if _wram(memory, base + _MAP_OBJECT_TYPE) & 0x0F == 2:
            return 'npc'
        if sprite in {0x54, 0x55, 0x56}:
            return 'obstacle'
    return 'unknown'
