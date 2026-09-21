"""Small helpers for treating visible item objects as route opportunities."""

from .gold97_opening import _route


_ITEM_KINDS = frozenset({"item", "itemball", "item_ball", "pickup", "collectible"})
_STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def is_item_entity(entity):
    """Return true for an entity explicitly identified as a collectible.

    The sprite capture layer deliberately does not guess whether an unknown sprite
    is an NPC or an item. Adapters that know the object type can provide ``kind``
    (or ``is_item``); the key prefix is supported for lightweight callers and tests.
    """
    if bool(getattr(entity, "is_item", False)):
        return True
    for attribute in ("kind", "entity_type", "object_type", "type"):
        value = getattr(entity, attribute, None)
        if isinstance(value, str) and value.strip().lower() in _ITEM_KINDS:
            return True
    key = str(getattr(entity, "key", "")).strip().lower()
    return key.startswith(("item:", "itemball:", "pickup:"))


def item_cell(entity):
    """Convert a captured 16-pixel sprite anchor to its map cell."""
    pixel_x = getattr(entity, "pixel_x", None)
    pixel_y = getattr(entity, "pixel_y", None)
    if pixel_x is None or pixel_y is None:
        return None
    return int(pixel_x) // 16, int(pixel_y) // 16


def item_action(memory, state, entities, *, terrain=None, avoid=(), attempted=()):
    """Return a first step toward the nearest visible item, or ``None``.

    Item cells are object tiles rather than walkable destinations. Route to a free
    neighboring cell, then let the controller press A while the item is adjacent.
    ``attempted`` prevents an object that failed to disappear immediately after a
    pickup message from stealing the route forever.
    """
    if state.x is None or state.y is None or not state.map_group:
        return None
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    origin = (state.x, state.y)
    attempted = set(attempted)
    targets = sorted({cell for entity in entities if is_item_entity(entity)
                      for cell in (item_cell(entity),)
                      if cell is not None and (key, cell) not in attempted},
                     key=lambda cell: abs(cell[0] - origin[0]) + abs(cell[1] - origin[1]))
    if not targets:
        return None
    target = targets[0]
    if abs(target[0] - origin[0]) + abs(target[1] - origin[1]) == 1:
        return "a"
    neighbors = []
    for direction, (dx, dy) in _STEPS.items():
        neighbor = (target[0] + dx, target[1] + dy)
        if (0 <= neighbor[0] < state.map_width and
                0 <= neighbor[1] < state.map_height and neighbor != origin and
                (terrain is None or terrain.allows(neighbor, direction))):
            neighbors.append((abs(neighbor[0] - origin[0]) +
                              abs(neighbor[1] - origin[1]), neighbor))
    for _, neighbor in sorted(neighbors):
        action = _route(memory.map(key), origin, neighbor,
                        state.map_width, state.map_height, avoid=avoid,
                        terrain=terrain)
        if action:
            return action
    return None
