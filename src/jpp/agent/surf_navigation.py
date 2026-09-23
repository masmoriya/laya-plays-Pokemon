"""Reach a verified route exit across water with a learned, unlocked Surf."""
from collections import deque

from ..field_moves import field_ready
from ..gold97_collision import _WALL, _WATER
from .gold97_navigation import STEPS


def surf_exit_candidate(state, memory, terrain, reachable, destination, reward):
    if (not destination or terrain is None or not field_ready(state, 'Surf')
            or not any('SURF' in {move.upper().replace('_', ' ')
                                 for move in getattr(mon, 'moves', ())}
                       for mon in getattr(state, 'party', ()))):
        return None
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    collision = getattr(terrain, 'collision', None) or terrain
    blocked = {(tuple(cell), direction) for cell, direction in memory.map(key)['blocked']}
    objects = {tuple(npc['cell']) for npc in memory.world.get('journey_strategy', {}).get(
        'npcs', {}).values() if npc.get('map') == key and npc.get('visible')}
    exits = [(x, y, f'{group:02X}:{number:02X}')
             for x, y, _, group, number in getattr(state, 'map_exits', ())]
    # Some large maps do not expose distant warps in the live exit table until
    # the camera reaches them. A pinned atlas coordinate is still safe to
    # approach when the current cartridge collision map independently proves
    # the full Surf crossing and the dry path cannot reach that cell.
    from .travel_atlas import atlas
    exits.extend((edge['cell'][0], edge['cell'][1], edge['to'])
                 for edge in atlas()['edges'].get(key, ())
                 if edge['to'] == destination and 'cell' in edge)
    for x, y, exit_destination in dict.fromkeys(exits):
        if exit_destination != destination:
            continue
        exit_cell = (x, y)
        if exit_cell in reachable:
            continue
        path = _water_path(state, collision, blocked, objects, exit_cell)
        if not path:
            continue
        first_water = next((index for index, point in enumerate(path)
                            if collision.tile(point) in _WATER), None)
        if first_water is None or first_water == 0:
            continue
        shore, water = path[first_water - 1:first_water + 1]
        if shore not in reachable:
            continue
        direction = next((name for name, (dx, dy) in STEPS.items()
                          if (shore[0] + dx, shore[1] + dy) == water), None)
        if not direction or (shore, direction) in blocked:
            continue
        return {
            'id': f'surf:{key}:{x}:{y}:{destination}', 'kind': 'exit',
            'map': key, 'cell': list(shore), 'direction': direction,
            'destination_key': destination, 'destination': _destination_name(state, destination),
            'target_cell': [x, y], 'surf_activation': True,
            'label': f'Use Surf at {list(shore)} to reach {_destination_name(state, destination)}',
            'completion': f'Confirm Surf use and observe arrival in {_destination_name(state, destination)}',
            'goal_route': True, 'travel_route': True, 'prerequisite': True,
            'journey_reward': reward * 4, 'path_steps': reachable.distances[shore],
            'reward_reason': 'Surf is learned, badge-ready, and needed for the verified route exit',
            'destination_evidence': 'observed map exit across collision-verified water',
        }
    return None


def _destination_name(state, destination):
    from .travel_atlas import name
    return name(destination)


def _water_path(state, terrain, blocked, objects, goal):
    start = (state.x, state.y)
    previous = {start: None}
    queue = deque([start])
    while queue:
        point = queue.popleft()
        if point == goal:
            break
        for direction, (dx, dy) in STEPS.items():
            target = point[0] + dx, point[1] + dy
            tile = terrain.tile(target)
            if (target in previous or target in objects or tile is None or tile in _WALL
                    or (point, direction) in blocked
                    or (not terrain.allows(target, direction) and tile not in _WATER)):
                continue
            previous[target] = point
            queue.append(target)
    if goal not in previous:
        return []
    path, point = [], goal
    while point is not None:
        path.append(point)
        point = previous[point]
    return list(reversed(path))
