"""Resume a goal route using exits already observed in the cartridge."""
from collections import deque
import re

from .journey_exits import _area_name
from .journey_guidance import _terms, _GENERIC, _OPTIONAL


def rank_known_routes(targets, state, memory, goal, reward, *, required_next_map=None):
    # The pinned itinerary is authoritative when available. This graph is
    # inferred from previously traversed exits and can send a multi-stop goal
    # back toward an earlier town named in the same objective. On long routes
    # that also hides the frontier toward the actual next gate.
    if required_next_map:
        return targets
    if not _terms(goal) & {'city', 'town', 'gate', 'route', 'port', 'mine', 'gym', 'tower', 'forest', 'cave', 'aquarium'}:
        return targets
    data = memory.world['journey_strategy']
    graph = {key: set(destinations) for key, destinations in data.get('map_exits', {}).items()}
    if any('discovery' in area for area in memory.world.get('maps', {}).values()):
        graph = {key: {f'{e[3]:02X}:{e[4]:02X}' for e in area.get('discovery', {}).get('exits', ()) if e[3] and e[4]}
                 for key, area in memory.world['maps'].items()}
    for edge in data['connections']:
        graph.setdefault(edge['from'], set()).add(edge['to'])
    nodes = set(graph) | {node for adjacent in graph.values() for node in adjacent}
    from .journey_prerequisites import ferry_goal
    milestone = next((i for i in range(1, 128) if i not in
                      memory.world.get('route', {}).get('completed', ())), None)
    if ferry_goal(state, milestone) and {'0E:01', '0E:02'} <= nodes:
        # Verified ferry script links these observed ports even though it is
        # not a doorway in either map's warp table.
        graph.setdefault('0E:01', set()).add('0E:02')
    goal_terms = _terms(goal) - _GENERIC - _OPTIONAL - {'gym', 'gate', 'port'}
    goal_terms = {term for term in goal_terms if not term.isdigit()}
    # A shared city prefix does not make its port, shop or radio tower the goal.
    full_goal = _terms(goal)
    named_terms = {node: {term for term in _terms(_area_name(node))
                         if not re.fullmatch(r'b?\d+f', term)} for node in nodes}
    exact = {node for node in nodes if named_terms[node] <= full_goal}
    matches = {node: (len(_terms(_area_name(node)) & goal_terms)
                     if not exact or node in exact else 0) for node in nodes}
    best = max(matches.values(), default=0)
    if not best:
        return targets
    destinations = {node for node, score in matches.items() if score == best}
    current = f'{state.map_group:02X}:{state.map_number:02X}'
    if current in destinations:
        return targets  # Local interactions own the decision once there.
    reverse = {}
    for source, adjacent in graph.items():
        for destination in adjacent:
            reverse.setdefault(destination, set()).add(source)
    distance = dict.fromkeys(destinations, 0)
    queue = deque(destinations)
    while queue:
        node = queue.popleft()
        for source in reverse.get(node, ()):
            if source not in distance:
                distance[source] = distance[node] + 1
                queue.append(source)
    remaining = distance.get(current)
    if remaining is None:
        return targets
    for target in targets:
        if (target['kind'] == 'exit'
                and distance.get(target.get('destination_key'), remaining) < remaining):
            target.update(goal_route=True, journey_reward=reward * 2,
                          reward_reason='Observed exits lead toward the current Journey goal')
    return sorted(targets, key=lambda target: -target.get('journey_reward', 0))
