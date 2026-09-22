"""Observed shortest paths and retracing costs, with reusable search results."""
import heapq
import json
from functools import lru_cache
from itertools import count

from .gold97_navigation import STEPS


class ReachablePaths(dict):
    def __init__(self, headings, distances):
        super().__init__(headings)
        self.distances = distances


def paths(state, memory, terrain, *, prefer_new=True):
    """One observed-path search, preferring edges not repeatedly retraced."""
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    memory.expire_blocked(key)
    origin = (state.x, state.y)
    blocked = frozenset((tuple(p), d) for p, d in memory.map(key)["blocked"])
    objects = frozenset(tuple(n["cell"]) for n in memory.world.get("journey_strategy", {}).get(
        "npcs", {}).values() if n["map"] == key and n.get("outcome") != "collected"
                and (n.get("visible", False) or n.get("category") in {"item", "obstacle", "resource"}))
    from .navigation_trace import edge_costs
    from .discovery import known_exits
    portals = frozenset(tuple(e[:2]) for e in known_exits(state, terrain))
    return _paths(origin, state.map_width, state.map_height, terrain, blocked, objects,
                  edge_costs(memory, key) if prefer_new else (), portals)


@lru_cache(maxsize=32)
def _paths(origin, width, height, terrain, blocked, objects, costs=(), portals=frozenset()):
    prices = {(tuple(p), d): count for stamp, count in costs for p, d in [json.loads(stamp)]}
    found, distances = {origin: None}, {origin: 0}
    serial = count()
    queue = [(0, next(serial), origin)]
    while queue:
        cost, _, point = heapq.heappop(queue)
        if cost != distances[point] or (point in portals and point != origin):
            continue
        for direction, (dx, dy) in STEPS.items():
            target = point[0] + dx, point[1] + dy
            if (target in objects or (point, direction) in blocked
                    or not (0 <= target[0] < width and 0 <= target[1] < height)
                    or terrain is None or not terrain.allows(target, direction)):
                continue
            price = cost + 1 + min(6, prices.get((point, direction), 0))
            if price < distances.get(target, float('inf')):
                distances[target] = price
                found[target] = found[point] or direction
                heapq.heappush(queue, (price, next(serial), target))
    return ReachablePaths(found, distances)
