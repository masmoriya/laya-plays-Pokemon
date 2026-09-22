"""Turn an owned HM into a specific party, storage, badge, or capture subgoal."""
from ..field_moves import normalize
from .journey_hms import hm_journey


def compatible(mon, move):
    return (normalize(move) in {normalize(m) for m in getattr(mon, 'moves', ())}
            or move in getattr(getattr(mon, 'species_data', None), 'field_moves', ()))


def preparation(state, milestone, memory=None):
    journey = hm_journey(state, milestone)
    focus = journey['active']
    if not focus or not focus['owned']:
        return {'next': journey['instruction']}
    move = focus['name']
    boxed = [m for m in getattr(state, 'box_roster', ()) if compatible(m, move)] if getattr(state, 'storage_verified', False) else []
    seen = (memory.world.get('hm_encounters', {}).get(move, []) if memory else [])
    if focus['action'] == 'teach':
        action, next_step = 'teach', focus['label']
    elif focus['compatible_slots']:
        action, next_step = 'moves', f'{move} has a compatible party member but no safe move replacement; keep existing HMs'
    elif boxed:
        action, next_step = 'withdraw', f'Use a Center PC to bring {boxed[0].species} for {move}'
    elif not focus['badge_ready']:
        action = 'badge'
        from ..field_moves import BY_NAME
        spec = BY_NAME[normalize(move)]
        next_step = f'Defeat {spec.leader} for the {spec.badge_name}; catch a compatible Pokemon when encountered'
    else:
        action = 'catch'
        next_step = f'Find a verified {move}-compatible Pokemon; do not reopen the HM menu with the unchanged party'
    return {'move': move, 'action': action, 'next': next_step,
            'party_compatible': focus['compatible_slots'],
            'storage_checked': bool(getattr(state, 'storage_verified', False)),
            'boxed': [m.species for m in boxed[:3]], 'seen_at': seen[-3:],
            'badge_ready': focus['badge_ready']}


def observe_encounter(memory, state):
    if not getattr(state, 'mechanics_verified', False):
        return
    battle = getattr(state, 'battle', None)
    foe = getattr(battle, 'opponent', None)
    if getattr(battle, 'kind', None) != 'wild' or foe is None:
        return
    from .gold97_services import novel_capture
    if not novel_capture(state, foe):
        return  # Preserve the run's collection policy.
    for move in getattr(getattr(foe, 'species_data', None), 'field_moves', ()):
        row = {'map': f'{state.map_group:02X}:{state.map_number:02X}',
               'species': foe.species, 'cell': [state.x, state.y]}
        rows = memory.world.setdefault('hm_encounters', {}).setdefault(move, [])
        if row not in rows:
            rows.append(row)
            del rows[:-12]
            memory.save()


def rank_preparation(targets, state, milestone, reward, memory):
    focus = preparation(state, milestone, memory)
    destinations = set()
    if focus.get('action') == 'withdraw':
        from .gold97_services import CENTER_ENTRANCES
        destinations = {'%02X:%02X' % entry[1] for entry in CENTER_ENTRANCES.values()}
    elif focus.get('action') == 'catch':
        destinations = {row['map'] for row in focus.get('seen_at', [])}
    current = f'{state.map_group:02X}:{state.map_number:02X}'
    # Choose the nearest observed destination, rather than rewarding exits
    # toward every Center and allowing a new PC detour at each intersection.
    hops = nearest_hops(memory, current, destinations)
    for target in targets:
        forward = target['kind'] == 'exit' and target.get('destination_key') in hops
        # An unknown acquisition location is a planning question, not evidence
        # that every camera viewpoint advances the missing capability.
        local = (focus.get('action') == 'catch' and current in destinations
                 and target['kind'] == 'explore' and not target.get('reobserve_interaction'))
        if forward or local:
            target.update(prerequisite=True, investigation_priority=True,
                          journey_reward=reward * 4, label=focus['next'],
                          reward_reason='Resolve missing HM party capability')
    return sorted(targets, key=lambda t: -t.get('journey_reward', 0))


def nearest_hops(memory, current, destinations):
    if not destinations or current in destinations:
        return set()
    from collections import deque
    data = memory.world.get('journey_strategy', {})
    edges = {}
    for connection in data.get('connections', ()):
        edges.setdefault(connection['from'], set()).add(connection['to'])
    for source, exits in data.get('map_exits', {}).items():
        edges.setdefault(source, set()).update(exits)
    queue, visited = deque([(current, None)]), {current}
    while queue:
        source, first = queue.popleft()
        for dest in sorted(edges.get(source, ())):
            if dest in visited:
                continue
            hop = first or dest
            if dest in destinations:
                return {hop}
            visited.add(dest)
            queue.append((dest, hop))
    return destinations  # A directly observed candidate can establish the first hop.
