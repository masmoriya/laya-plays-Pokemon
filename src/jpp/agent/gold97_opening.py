"""Verified v6.1c opening goals, with replanning around observed collisions."""

from heapq import heappop, heappush


_STEPS = {"up": (0, -1), "down": (0, 1),
          "left": (-1, 0), "right": (1, 0)}
# Walkable cells verified in the cartridge on both sides of the bed. A plain
# Manhattan route can otherwise wander into the lower room and never reach PC.
_BEDROOM_CORRIDOR = ({(x, 3) for x in range(5, 10)}
                     | {(4, 4), (5, 4), (5, 5), (6, 2), (9, 2), (9, 1), (9, 0)}
                     | {(x, 5) for x in range(3, 6)}
                     | {(3, y) for y in range(2, 6)})


def _route(area, start, target, width, height, *, avoid=(), allowed=None,
           terrain=None):
    """Choose a target-directed step; observed blocked edges are expensive."""
    blocked = {(tuple(point), direction) for point, direction in area["blocked"]}
    visited = {tuple(point) for point in area["visited"]}
    avoid = set(avoid)
    queue = [(0, 0, start, None)]
    best = {start: 0}
    serial = 0
    while queue:
        cost, _, point, first = heappop(queue)
        if cost != best[point]:
            continue
        if point == target:
            return first
        for direction, (dx, dy) in _STEPS.items():
            neighbor = (point[0] + dx, point[1] + dy)
            if not (0 <= neighbor[0] < width and 0 <= neighbor[1] < height):
                continue
            if terrain is not None and not terrain.allows(neighbor, direction):
                continue
            if neighbor in avoid and neighbor != target:
                continue
            if allowed is not None and neighbor not in allowed and neighbor != target:
                continue
            # A known wall can be retried if the map memory has no other path.
            # Successful movement clears that edge in Gold97Memory.
            price = 100 if (point, direction) in blocked else (
                terrain.cost(neighbor) if terrain is not None else 1)
            candidate = cost + price + (0.05 if neighbor in visited else 0)
            if candidate >= best.get(neighbor, float("inf")):
                continue
            best[neighbor] = candidate
            serial += 1
            heappush(queue, (candidate, serial, neighbor, first or direction))
    return None


class Gold97Opening:
    """Own only the known opening; the ordinary policy owns later play."""

    def __init__(self):
        self.facing_goal = None

    def choose(self, state, memory, *, overworld, terrain=None):
        if state.map_group != 20 or not hasattr(state, "read_oaks_email"):
            return None
        number = state.map_number
        party = bool(state.party)
        scene = state.opening_scene
        if state.in_battle:
            if number == 4 and scene == 3 and state.battle.kind == "trainer":
                return "Resolve the first rival battle", "a"
            return None
        if not overworld:
            if number == 5 and party and scene == 1:
                # B advances text and declines the optional nickname prompt.
                return "Finish choosing Flambear", "b"
            return None
        if state.x is None or state.y is None:
            return None
        if number == 7:
            goal, target, arrival = (
                ("Read Oak's email on the PC", (3, 2), "a")
                if not state.read_oaks_email else
                ("Go downstairs after reading Oak's email", (9, 0), "up")
            )
        elif number == 6:
            if scene == 0:
                return "Finish Mom's opening conversation", "wait"
            goal, target, arrival = "Leave home for Silent Town", (6, 7), "down"
        elif number == 3:
            if not party and scene == 0:
                return "Finish the rival's introduction", "wait"
            if not party:
                goal, target, arrival = "Meet Blue west of town", (1, 16), "wait"
            else:
                goal, target, arrival = "Reach Route 101", (0, 16), "left"
                # The lab doorway is a warp in both directions. Step away
                # before planning west, and never route back through it.
                if (state.x, state.y) in {(14, 19), (15, 19)}:
                    return goal, "down"
        elif number == 4:
            if not party and scene == 0:
                goal, target, arrival = "Return to Blue in town", (3, 15), "down"
            elif not party or scene == 1:
                return "Follow Blue into Oak's lab", "wait"
            elif scene == 4:
                goal, target, arrival = "Meet Daisy for supplies", (4, 11), "wait"
            elif scene == 2:
                goal, target, arrival = "Leave Oak's lab entrance", (4, 15), "down"
            else:
                goal, target, arrival = "Walk toward Daisy", (4, 11), "wait"
        elif number == 5:
            if not party and scene == 0:
                return "Listen to Oak's introduction", "wait"
            if not party:
                goal, target, arrival = "Choose Flambear", (5, 3), "a"
            elif scene == 1:
                return "Finish receiving Flambear", "wait"
            else:
                goal, target, arrival = "Leave Oak's lab", (3, 7), "down"
        else:
            return None
        position = (state.x, state.y)
        if position != target:
            self.facing_goal = None
            key = f"{state.map_group:02X}:{number:02X}"
            avoid = {(14, 19), (15, 19)} if number == 3 and party else ()
            allowed = (_BEDROOM_CORRIDOR if number == 7 and position in _BEDROOM_CORRIDOR
                       else None)
            action = _route(memory.map(key), position, target,
                            state.map_width, state.map_height,
                            avoid=avoid, allowed=allowed, terrain=terrain)
            return (goal, action or "wait")
        if arrival == "a":
            marker = (number, target)
            if self.facing_goal != marker:
                self.facing_goal = marker
                return goal, "up"
        return goal, arrival
