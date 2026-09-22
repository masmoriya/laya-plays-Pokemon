"""Shortest known route to a genuinely unexplored adjacent map cell."""

from collections import deque


STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def frontier_step(area, origin, width, height, *, terrain=None, avoid=()):
    """Return a known-path first step only when no local frontier is available."""
    avoid = set(avoid)
    visited = {tuple(point) for point in area["visited"]}
    blocked = {(tuple(point), direction) for point, direction in area["blocked"]}
    edges = {(tuple(point), direction) for point, direction in area["edges"]}

    def candidates(point):
        for direction, (dx, dy) in STEPS.items():
            target = (point[0] + dx, point[1] + dy)
            if (0 <= target[0] < width and 0 <= target[1] < height and
                    (point, direction) not in blocked and target not in avoid and
                    (terrain is None or terrain.allows(target, direction))):
                yield direction, target

    if any(target not in visited for _, target in candidates(origin)):
        return None
    queue = deque([(origin, None)])
    seen = {origin}
    while queue:
        point, first = queue.popleft()
        if point != origin and any(target not in visited for _, target in candidates(point)):
            return first
        for direction, target in candidates(point):
            if (point, direction) in edges and target not in seen:
                seen.add(target)
                queue.append((target, first or direction))
    return None


class MovementHistory:
    """Detect revisits across successful moves, including map transitions."""

    def __init__(self):
        self.points = []

    def observe(self, key, position):
        point = (key, position)
        if not self.points or self.points[-1] != point:
            self.points.append(point)
            # Keep enough history to catch short stair/door cycles without
            # treating a legitimate return much later in the journey as a loop.
            self.points = self.points[-24:]

    @property
    def looping(self):
        return bool(self.points and self.points.count(self.points[-1]) >= 3)

    def choose(self, key, position, options):
        moves = [direction for direction in options if direction in STEPS]
        if not moves:
            return next(iter(options))
        return min(moves, key=lambda direction: self.points.count((key, (
            position[0] + STEPS[direction][0], position[1] + STEPS[direction][1]))))
