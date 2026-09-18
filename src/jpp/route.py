"""The v0.1 route: one waypoint per map, axis-first stepping, a local sidestep.

Not a pathfinder. v0.1 walks six maps whose connections are static and public, so the
route is a hand-written list of tiles, most of them `warp_event` coordinates straight out
of `data/maps/objects/*.asm`. Anything past Viridian needs a real occupancy map with warp
edges, which is the v0.2 item in CONTEXT section 2.

`ponytail:` the indoor tiles are exact (they are warp coordinates in the source). The two
outdoor legs, Pallet Town's north exit and the walk up Route 1, are a straight line up the
middle of a map whose width is known from `map_constants.asm` but whose walkable column is
not. Confirm both with `jpp probe` on a real ROM; the ceiling is the learned map.
"""

from . import symbols as S

DIRECTIONS = ("up", "down", "left", "right")

# One target tile per map, per goal. (x, y) in map tile coordinates, the same units as
# wXCoord / wYCoord.
WAYPOINTS: dict[str, dict[int, tuple[int, int]]] = {
    # RedsHouse2F.asm: warp_event 7, 1, REDS_HOUSE_1F, 3
    # RedsHouse1F.asm: warp_event 2, 7, LAST_MAP, 1
    "leave_house": {
        S.REDS_HOUSE_2F: (7, 1),
        S.REDS_HOUSE_1F: (2, 7),
    },
    # PalletTown.asm: warp_event 12, 11, OAKS_LAB, 2
    # OaksLab.asm: object_event 5, 2, SPRITE_OAK -> stand one tile below him
    "get_starter": {
        S.PALLET_TOWN: (12, 11),
        S.OAKS_LAB: (5, 3),
    },
    # the rival battle happens where we stand; no walking
    "win_lab_rival": {},
    # PALLET_TOWN is 10x9 blocks, ROUTE_1 10x18: head north up the middle
    "reach_viridian": {
        S.PALLET_TOWN: (10, 0),
        S.ROUTE_1: (10, 0),
    },
}

# Where the player stands in the 20x18 tile grid `game_area_collision()` returns, and how
# many grid tiles one walking step covers.
# ponytail: measured from the screen geometry, not from a running ROM. `jpp probe` prints
# the grid; if the player is not at this cell the sidestep reads the wrong neighbours.
PLAYER_COL, PLAYER_ROW = 8, 9
STEP_TILES = 2
WALKABLE = 0

_DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def waypoint_for(goal, state) -> tuple[int, int] | None:
    """The tile to head for on the current map, or None if this map has no waypoint."""
    return WAYPOINTS.get(goal.name, {}).get(state.map_id)


def next_step(state, waypoint) -> str | None:
    """Axis-first greedy: close x, then y. None once the tile is reached."""
    if waypoint is None:
        return None
    dx = waypoint[0] - state.x
    dy = waypoint[1] - state.y
    if dx:
        return "right" if dx > 0 else "left"
    if dy:
        return "down" if dy > 0 else "up"
    return None


def distance(state, waypoint, direction=None) -> int:
    dx, dy = _DELTA.get(direction, (0, 0))
    return abs(waypoint[0] - (state.x + dx)) + abs(waypoint[1] - (state.y + dy))


def free_directions(collision) -> list[str]:
    """Which of the four neighbours the collision grid says are walkable."""
    free = []
    for name, (dx, dy) in _DELTA.items():
        col = PLAYER_COL + dx * STEP_TILES
        row = PLAYER_ROW + dy * STEP_TILES
        if 0 <= row < len(collision) and 0 <= col < len(collision[row]):
            if collision[row][col] == WALKABLE:
                free.append(name)
    return free


def sidesteps(state, collision, waypoint) -> list[str]:
    """Free neighbours that do not walk away from the waypoint.

    One survivor is a plain move. Two or more that are equally far is the tie Jev breaks,
    which is the only place the model touches the overworld.
    """
    if waypoint is None:
        return []
    free = free_directions(collision)
    if not free:
        return []
    best = min(distance(state, waypoint, d) for d in free)
    if best >= distance(state, waypoint):
        return []  # every free neighbour is a step backwards: nothing to choose between
    return [d for d in free if distance(state, waypoint, d) == best]
