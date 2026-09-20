"""Verified map exits for the next Gold 97 Journey leg."""

from .gold97_opening import _route


# The Route 101 north gate and its Pagota exit come from the v6.1c map events.
_PAGOTA_LEG = {
    (20, 10): (4, 0),
}

# Entrance and stair warps in the v6.1c Pagota/Brass Tower map events.
_BRASS_TOWER_LEG = {
    (3, 1): (0, 1),
    (3, 2): (11, 4),
    (3, 3): (10, 1),
    (3, 4): (11, 11),
    (3, 5): (0, 5),
}

# A low-grass corridor through Silent Hills, derived from the v6.1c map's
# collision cells. The direct diagonal to (6, 0) crosses impassable ridges.
_HILLS_WAYPOINTS = (
    (42, 30), (42, 21), (39, 21), (39, 16), (40, 16), (40, 15),
    (42, 15), (42, 13), (40, 13), (40, 10), (36, 10), (36, 18),
    (36, 19), (35, 19), (34, 19), (34, 20),
    (30, 20), (30, 18), (24, 18), (24, 20),
    (16, 20), (16, 22), (12, 22), (12, 24), (10, 24), (10, 28),
    (6, 28), (6, 0),
)


def _hills_target(state, memory):
    nav = getattr(memory, "world", {}).setdefault("nav", {})
    index = int(nav.get("silent_hills_waypoint", 0))
    if state.x >= 48 and state.y >= 28:
        index = 0
    position = (state.x, state.y)
    while index < len(_HILLS_WAYPOINTS) - 1 and position == _HILLS_WAYPOINTS[index]:
        index += 1
    if nav.get("silent_hills_waypoint") != index:
        nav["silent_hills_waypoint"] = index
        if hasattr(memory, "save"):
            memory.save()
    return _HILLS_WAYPOINTS[index]


def journey_step(state, memory, route, *, overworld, avoid=(), terrain=None):
    """Return a verified route action when the current milestone has one."""
    if route.now not in (3, 4) or not overworld or state.in_battle:
        return None
    if route.now == 4:
        if (state.map_group, state.map_number) == (9, 12):
            target = (3, 7)
        elif (state.map_group, state.map_number) == (9, 2):
            target = ((11, 17) if getattr(state, "talked_to_kurt_and_falkner", False)
                      else (3, 31))
        else:
            target = _BRASS_TOWER_LEG.get((state.map_group, state.map_number))
    else:
        target = _PAGOTA_LEG.get((state.map_group, state.map_number))
    if route.now == 3 and (state.map_group, state.map_number) == (20, 2):
        target = (30, 28) if state.x > 20 or state.y > 29 else (8, 5)
    elif route.now == 3 and (state.map_group, state.map_number) == (3, 50):
        target = _hills_target(state, memory)
        if state.y == 0 and state.x in (6, 7):
            return "Exit Silent Hills to Route 101", "up"
    if route.now == 3 and (state.map_group, state.map_number) == (20, 10) and state.y == 0:
        return "Exit the Pagota gate", "up"
    if route.now == 4 and (state.map_group, state.map_number) == (9, 12):
        if state.y == 7 and state.x in (3, 4):
            return "Leave Kurt's house", "down"
    if target is None or state.x is None or state.y is None:
        return None
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    action = _route(memory.map(key), (state.x, state.y), target,
                    state.map_width, state.map_height, avoid=avoid,
                    terrain=terrain)
    goal = "Climb Brass Tower" if route.now == 4 else "Reach Pagota City via Route 101"
    return (goal, action) if action else None
