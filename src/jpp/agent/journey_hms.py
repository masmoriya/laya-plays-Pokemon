"""HM substeps keep story IDs stable while making missing prerequisites actionable."""
from ..field_moves import capabilities, BY_NAME
from .gold97_learning import replacement_index
from .gold97_mechanics import REFERENCE


def capability_key(state):
    return (getattr(state, 'mechanics_verified', False),
            tuple(getattr(state, 'owned_hms', ())), tuple(getattr(state, 'badge_ids', ())),
            tuple((getattr(mon, 'identity', None), tuple(getattr(mon, 'moves', ())))
                  for mon in getattr(state, 'party', ())))


def teaching_plan(state, row):
    if not row['owned'] or row['learned_slots']:
        return None
    for slot in sorted(row['compatible_slots'], key=lambda i: len(state.party[i].moves)):
        mon = state.party[slot]
        replacement = replacement_index(mon, row['name']) if len(mon.moves) == 4 else None
        if len(mon.moves) < 4 or replacement is not None:
            return {'move': row['name'], 'slot': slot, 'number': BY_NAME[row['name'].upper()].number,
                    'identity': mon.identity, 'before': tuple(mon.moves), 'replace': replacement}
    return None


def hm_journey(state, milestone):
    rows = capabilities(state, milestone)
    active = None
    for row in sorted(rows, key=lambda r: (not r['owned'], r['stage'])):
        if not row['due'] or row['ready'] or row['owned'] is None:
            continue
        if row['learned_slots']:
            continue  # Missing badge remains explicit; follow the story to that leader.
        if row['owned']:
            plan = teaching_plan(state, row)
            action = 'teach' if plan else 'party'
            label = (f"Teach {row['name']} to {state.party[plan['slot']].species}"
                     if plan else row['next'])
            active = {**row, 'action': action, 'label': label, 'teaching': plan}
            break
        # Story rewards are handled by their event, never by inventing an NPC.
        # A missed acquisition remains actionable after its scheduled stage.
        active = {**row, 'action': 'obtain', 'label': row['next'], 'teaching': None}
        break
    pending = [row for row in rows if row['due'] and not row['ready']]
    return {'moves': rows, 'active': active,
            'pending': [{'id': row['id'], 'next': row['next'], 'location': row['location']}
                        for row in pending],
            'instruction': (active['label'] + '. ' + (active['acquisition'] if active['action'] == 'obtain'
                            else 'Verify the learned move in the party before marking it ready.') if active else
                            '; '.join(row['next'] for row in pending) if pending else
                            'Follow the story; future HMs remain pending. '
                            'An owned HM is not proof of a learned or usable move.')}


def rank_hm_targets(targets, state, milestone, reward, memory=None):
    focus = hm_journey(state, milestone)['active']
    if not focus or focus['action'] != 'obtain':
        return targets
    dest = '%02X:%02X' % tuple(focus['source_map'])
    current = f'{state.map_group:02X}:{state.map_number:02X}'
    hops = acquisition_hops(memory, current, dest) if memory else {dest}
    for target in targets:
        forward = target.get('kind') == 'exit' and target.get('destination_key') in hops
        # Candidate's cell is the interaction approach, not the NPC itself.
        if current == dest and target.get('kind') == 'talk' and focus['source_cell']:
            from .gold97_navigation import STEPS
            dx, dy = STEPS.get(target.get('direction'), (0, 0))
            forward |= (target['cell'][0] + dx, target['cell'][1] + dy) == tuple(focus['source_cell'])
        if forward:
            target.update(prerequisite=True, investigation_priority=True, journey_reward=reward * 4,
                          label=focus['label'] + ' · ' + focus['location'],
                          source=REFERENCE['source'] + 'maps/' + focus['source_file'],
                          reward_reason='Missing HM acquisition substep')
    return sorted(targets, key=lambda t: -t.get('journey_reward', 0))


def acquisition_hops(memory, current, destination):
    """Recover missed HMs through observed exits without inventing a route."""
    from collections import deque
    reverse = {}
    data = memory.world.get('journey_strategy', {})
    edges = [(edge['from'], edge['to']) for edge in data.get('connections', ())]
    edges += [(key, dest) for key, destinations in data.get('map_exits', {}).items()
              for dest in destinations]
    edges += [(key, f'{exit[3]:02X}:{exit[4]:02X}')
              for key, area in memory.world.get('maps', {}).items()
              for exit in area.get('discovery', {}).get('exits', ()) if exit[3] and exit[4]]
    for source, dest in edges:
        reverse.setdefault(dest, set()).add(source)
    distance, queue = {destination: 0}, deque([destination])
    while queue:
        dest = queue.popleft()
        for source in reverse.get(dest, ()):
            if source not in distance:
                distance[source] = distance[dest] + 1
                queue.append(source)
    remaining = distance.get(current)
    return ({dest for source, dest in edges if source == current
             and distance.get(dest, remaining) < remaining}
            if remaining is not None else {destination})
