"""Checkpoint-owned observed collision data; raw maps never reach planning."""
from dataclasses import dataclass
from ..gold97_collision import Gold97CollisionMap


@dataclass(frozen=True)
class ObservedTerrain(Gold97CollisionMap):
    seen: frozenset = frozenset()
    visible: frozenset = frozenset()
    exits: tuple = ()
    known_edges: frozenset = frozenset()
    visible_objects: frozenset = frozenset()

    def tile(self, point):
        return super().tile(point) if tuple(point) in self.seen else None

    def allows(self, point, direction):
        if self.tile(point) is not None:
            return super().allows(point, direction)
        steps = {'up': (0,-1), 'down': (0,1), 'left': (-1,0), 'right': (1,0)}
        dx, dy = steps.get(direction, (0,0))
        return ((point[0]-dx, point[1]-dy), direction) in self.known_edges


def observe_terrain(memory, state, terrain, overworld):
    if terrain is None:
        return None
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    area = memory.map(key)
    discovery = area.setdefault('discovery', {'tiles': {}, 'exits': []})
    visible = frozenset(getattr(terrain, 'visible_cells', ()) or ()) if overworld else frozenset()
    changed = False
    if (state.x, state.y) in visible:
        memory.visited(key, (state.x, state.y))
    for x, y in visible:
        value = terrain.tile((x, y))
        cell = f'{x},{y}'
        if value is not None and discovery['tiles'].get(cell) != value:
            discovery['tiles'][cell] = value
            changed = True
    for exit in getattr(state, 'map_exits', ()):
        if tuple(exit[:2]) not in visible:
            continue
        observed = [*exit[:3], 0, 0]  # Seeing a door does not reveal its destination.
        for connection in memory.world.get('journey_strategy', {}).get('connections', ()):
            if (connection['from'] == key and connection['at'] == list(exit[:2])
                    and connection['to'] == f'{exit[3]:02X}:{exit[4]:02X}'):
                observed[3:] = [int(part, 16) for part in connection['to'].split(':')]
                break
        old = next((e for e in discovery['exits'] if e[:3] == observed[:3]), None)
        if old != observed:
            if old is not None:
                discovery['exits'].remove(old)
            discovery['exits'].append(observed)
            changed = True
    cells = bytearray([255]) * (terrain.width * terrain.height)
    seen = set()
    for cell, value in discovery['tiles'].items():
        x, y = map(int, cell.split(','))
        if 0 <= x < terrain.width and 0 <= y < terrain.height:
            cells[y * terrain.width + x] = value
            seen.add((x, y))
    if changed:
        memory.world['discovery_revision'] = memory.world.get('discovery_revision', 0) + 1
        memory.save()
    return ObservedTerrain(terrain.map_key, terrain.width, terrain.height, bytes(cells),
                           seen=frozenset(seen), visible=visible,
                           visible_objects=frozenset(getattr(terrain, "entity_cells", ()) or visible) if overworld else frozenset(),
                           exits=tuple(tuple(e) for e in discovery['exits']),
                           known_edges=frozenset((tuple(p), d) for p, d in area.get('edges', ())))


def known_exits(state, terrain):
    return terrain.exits if isinstance(terrain, ObservedTerrain) else getattr(state, 'map_exits', ())


def frontier_cells(reachable, terrain, visited):
    if not isinstance(terrain, ObservedTerrain):
        return [cell for cell in reachable if cell not in visited]
    # A viewpoint can reveal ground across a wall, not just adjacent floor.
    # Use a conservative inner viewport so this does not reveal hidden contents.
    return [cell for cell in reachable if any(
        0 <= cell[0]+dx < terrain.width and 0 <= cell[1]+dy < terrain.height
        and (cell[0]+dx, cell[1]+dy) not in terrain.seen
        for dx in range(-4, 5) for dy in range(-3, 4))]



class DisplayMemory:
    """Discovery storage for a dashboard without an attached agent."""
    def __init__(self):
        self.world = {'maps': {}}

    def map(self, key):
        return self.world['maps'].setdefault(key, {'visited': [], 'edges': [], 'blocked': []})

    def visited(self, key, point):
        cells = self.map(key)['visited']
        if list(point) not in cells:
            cells.append(list(point))

    def save(self):
        pass
