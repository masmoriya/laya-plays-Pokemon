"""Shortest known route to a genuinely unexplored adjacent map cell."""

from collections import deque


STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def frontier_step(area, origin, width, height):
    """Return a known-path first step only when no local frontier is available."""
    visited = {tuple(point) for point in area["visited"]}
    blocked = {(tuple(point), direction) for point, direction in area["blocked"]}
    edges = {(tuple(point), direction) for point, direction in area["edges"]}

    def candidates(point):
        for direction, (dx, dy) in STEPS.items():
            target = (point[0] + dx, point[1] + dy)
            if (0 <= target[0] < width and 0 <= target[1] < height and
                    (point, direction) not in blocked):
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
