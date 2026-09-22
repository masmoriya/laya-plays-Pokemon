"""Pinned map connectivity for planning; observed collision still owns movement."""
from collections import deque
from functools import lru_cache
import json
from pathlib import Path

from ..gold97_catalog import map_details


@lru_cache(maxsize=1)
def atlas():
    path = Path(__file__).resolve().parents[3] / 'config' / 'gold97_travel.json'
    if not path.exists():
        path = Path(__file__).resolve().parents[1] / 'resources' / path.name
    return json.loads(path.read_text())


@lru_cache(maxsize=512)
def name(key):
    return map_details(*(int(part, 16) for part in key.split(':')))[0]


def itinerary(state, destination):
    """Map hops are directions, never proof a gate is open or a trip completed."""
    if not getattr(state, 'mechanics_verified', False):
        return []
    start = f'{state.map_group:02X}:{state.map_number:02X}'
    graph = atlas()['edges']
    queue = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        if path[-1] == destination:
            return path
        for edge in graph.get(path[-1], ()):
            target = edge['to']
            # The Teknos bridge is a later story repair. Use the verified ferry
            # for the post-Whitney journey rather than assuming it is open.
            if path[-1] == '04:05' and (edge.get('direction') == 'north' or target == '04:0D'):
                continue
            if (target == '08:04' or path[-1] == '08:04') and not getattr(
                    state, 'route_103_slowpoke_cleared', False):
                continue
            if {path[-1], target} == {'0A:01', '08:04'}:
                continue  # The road is entered through Route 103 Westport Gate.
            if target not in seen:
                seen.add(target)
                queue.append(path + [target])
    return []


def travel_context(state, milestone):
    if not getattr(state, 'mechanics_verified', False):
        return None
    from ..route_progress import MAIN
    goal = MAIN.get(milestone, '').casefold()
    places = [node for node in atlas()['edges'] if name(node).casefold() in goal]
    destination = '08:05' if milestone in (16, 17) else '03:10' if milestone == 18 else max(places, key=lambda node: len(name(node)), default=None)
    blocked = milestone in (16, 17, 18) and not getattr(state, 'route_103_slowpoke_cleared', False)
    route = itinerary(state, destination) if destination and not blocked else []
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    return {
        'source': atlas()['source'],
        'destination': name(destination) if destination else None,
        'route': [{'map': node, 'name': name(node)} for node in route],
        'next_map': route[1] if len(route) > 1 else None,
        'next_stop': name(route[1]) if len(route) > 1 else None,
        'exits': [{**edge, 'name': name(edge['to'])} for edge in atlas()['edges'].get(key, ())],
        'instruction': ('Use the map route and reachable exits. Accept the Westport ferry at '
                        'Teknos Port boarding point (3, 9). Route 103 requires Whitney to '
                        'clear the Slowpoke. Finish any active phone call; travel does not '
                        'prove the call completed. Connectivity does not prove other story '
                        'gates or terrain passable. Incidental NPC dialogue is not a quest.'),
    }


def atlas_exits(state, reachable, excluded, terrain=None):
    """Expose map destinations only at cells the movement layer can reach."""
    if not getattr(state, 'mechanics_verified', False):
        return []
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    from .discovery import known_exits
    geometry = known_exits(state, terrain)
    result = []
    for edge in atlas()['edges'].get(key, ()):
        if edge.get('transport') and key != '0E:02':
            continue  # Westport's sailor is an interaction, not a doorway.
        direction = {'north': 'up', 'south': 'down', 'west': 'left', 'east': 'right'}.get(edge.get('direction'), '')
        if 'cell' in edge:
            cells = [tuple(edge['cell'])]
        else:
            cells = [cell for cell in reachable if
                     (direction == 'up' and cell[1] == 0) or
                     (direction == 'down' and cell[1] == state.map_height - 1) or
                     (direction == 'left' and cell[0] == 0) or
                     (direction == 'right' and cell[0] == state.map_width - 1)]
        for cell in cells:
            identifier = f'atlas:{key}:{cell[0]}:{cell[1]}:{edge["to"]}'
            visible_exit = next((e for e in geometry if tuple(e[:2]) == cell), None)
            if not edge.get('transport') and (not visible_exit or visible_exit[3] or visible_exit[4]):
                continue
            if cell not in reachable or identifier in excluded:
                continue
            if cell == (state.x, state.y) and not direction:
                continue  # Do not repeatedly activate a stationary warp.
            heading = direction or (visible_exit[2] if visible_exit else '')
            if not heading and terrain is not None and not edge.get('transport'):
                heading = {0x70: 'down', 0x76: 'left', 0x78: 'up', 0x7E: 'right'}.get(terrain.tile(cell), '')
            result.append({'id': identifier, 'kind': 'exit', 'cell': list(cell),
                           'direction': heading, 'map': key,
                           'destination_key': edge['to'], 'destination': name(edge['to']),
                           'label': edge.get('instruction', 'Travel to ' + name(edge['to'])),
                           'completion': 'Observe arrival in ' + name(edge['to']),
                           'source': atlas()['source']})
    return result


def rank_travel(targets, state, milestone, reward, memory=None):
    context = travel_context(state, milestone)
    next_map = context and context['next_map']
    if next_map:
        for target in targets:
            if target.get('destination_key') == next_map and not target.get('recent_return'):
                target.update(goal_route=True, travel_route=True, journey_reward=reward * 4,
                              reward_reason='Map route toward ' + context['destination'])
    if next_map and not any(t.get('travel_route') for t in targets):
        key = f'{state.map_group:02X}:{state.map_number:02X}'
        for target in targets:
            if target.get('destination_key') == key and not target.get('landing_return'):
                target.update(goal_route=True, travel_route=True, journey_reward=reward * 3,
                              reward_reason='Use passage stairs toward the next mapped exit')
    return sorted(targets, key=lambda item: -item.get('journey_reward', 0))


def rank_travel_frontier(targets, state, milestone, reward, memory=None):
    """Explore toward the next mapped doorway when it is not reachable yet."""
    # A map-level route does not prove that this walkable component reaches
    # an unseen edge. Keep speculative approach guidance to verified transfers.
    if milestone not in (16, 17, 18):
        return targets
    if any((t.get('goal_route') and not t.get('recent_return')) or t.get('goal_interaction')
           or t.get('reobserve_interaction') for t in targets):
        return targets
    context = travel_context(state, milestone)
    if not context or not context['next_map']:
        return targets
    edges = [e for e in context['exits'] if e['to'] == context['next_map']]
    from .passage_navigation import arrival_cell, at_entry
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    entry = arrival_cell(memory, key, context['next_map'], milestone)
    edges = [e for e in edges if not at_entry(e.get('cell'), entry)]
    def distance(cell):
        values = []
        for edge in edges:
            if 'cell' in edge:
                values.append(abs(cell[0]-edge['cell'][0]) + abs(cell[1]-edge['cell'][1]))
            else:
                values.append({'north': cell[1], 'south': state.map_height-1-cell[1],
                               'west': cell[0], 'east': state.map_width-1-cell[0]}[edge['direction']])
        return min(values, default=9999)
    frontier = [t for t in targets if t['kind'] == 'explore'
                and not t.get('reobserve_interaction')
                and distance(t['cell']) < distance((state.x, state.y))]
    if frontier:
        target = min(frontier, key=lambda t: distance(t['cell']))
        target.update(goal_route=True, travel_route=True, journey_reward=reward * 2,
                      label='Explore toward ' + name(context['next_map']),
                      reward_reason='Reveal a path toward the next mapped exit')
    return sorted(targets, key=lambda t: -t.get('journey_reward', 0))
