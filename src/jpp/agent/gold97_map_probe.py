"""Bounded movement checks when visual evidence contradicts collision memory."""


_STEPS = (("up", 0, -1), ("down", 0, 1),
          ("left", -1, 0), ("right", 1, 0))


def probe_options(state, memory, note):
    """Prefer Luna's visible openings, then test untried adjacent steps."""
    if state.x is None or state.y is None:
        return {}
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    position = (state.x, state.y)
    blocked = {(tuple(point), direction)
               for point, direction in memory.map(key)["blocked"]}
    candidates = {
        direction: f"test {direction} against uncertain map collision"
        for direction, dx, dy in _STEPS
        if (0 <= state.x + dx < state.map_width and
            0 <= state.y + dy < state.map_height and
            (position, direction) not in blocked)
    }
    suggested = set(note.get("walkable_directions") or ()) if (
        note and note.get("mode") == "overworld") else set()
    visual = {direction: candidates[direction] for direction, _, _ in _STEPS
              if direction in suggested and direction in candidates}
    return visual or candidates
