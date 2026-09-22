"""Evidence-based object outcomes and bounded contextual retries."""
import hashlib
import json
import re

RESOLVED_OUTCOMES = frozenset({'collected', 'harvested', 'exhausted', 'defeated', 'moved'})


def normalized(text):
    return ' '.join(text.upper().split())


def classify(npc):
    text = normalized(' '.join(npc.get('pages', ())))
    if npc.get('category') == 'resource':
        # A renewable object remains solid after harvesting. Merely reading
        # its description or finding a full bag never proves a pickup.
        result = resource_result(text)
        if result:
            npc.update(outcome=result, status='resolved')
    elif (re.search(r'\bPUT THE\b.+\bIN\b.+\bPOCKET\b', text)
            and not re.search(r"(?:CAN.?T|CANNOT|COULD NOT) PUT", text)):
        npc.update(category='item', outcome='collected', status='resolved')
    elif npc.get('outcome') != 'moved' and re.search(
            r'(?:MAY|MIGHT|COULD).{0,24}MOVE (?:THIS|IT)|TOO HEAVY|BIG BOULDER|MOVABLE'
            r'|(?:BOULDERS|HEAVY OBJECTS) MAY NOW BE MOVED|WANT TO USE STRENGTH', text):
        npc.update(category='obstacle', outcome='unresolved', status='pending')
    else:
        npc.setdefault('category', 'unknown')
        npc.setdefault('outcome', 'conversed' if npc.get('status') == 'talked' else 'seen')
    npc.setdefault('action_attempts', {})
    return npc


def resource_result(text):
    text = normalized(text)
    if re.search(r'\bOBTAINED\b.+[!.]|\bPUT THE\b.+\bIN\b.+\bPOCKET\b', text):
        if not re.search(r"(?:CAN.?T|CANNOT|COULD NOT) (?:PUT|CARRY)|(?:PACK|BAG) IS FULL", text):
            return 'harvested'
    if re.search(r"THERE.{0,8}NOTHING(?: HERE)?", text):
        return 'exhausted'
    return None


def evidence_key(state, npc, memory=None):
    inventory = tuple(sorted(n['id'] for n in memory.world.get('journey_strategy', {}).get('npcs', {}).values()
                             if n.get('outcome') == 'collected')) if memory else ()
    party = [(getattr(m, 'identity', None), tuple(getattr(m, 'moves', ())))
             for m in getattr(state, 'party', ())]
    data = (party, getattr(state, 'badge_ids', ()), getattr(state, 'poke_ball_count', None),
            npc.get('cell'), npc.get('pages', []), getattr(state, 'received_cut_from_bill', None),
            inventory, getattr(state, 'owned_hms', ()), getattr(state, 'strength_active', None))
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()[:16]


def eligible(npc, context, action='interact'):
    return (npc.get('outcome') not in RESOLVED_OUTCOMES
            and npc.get('action_attempts', {}).get(context, {}).get(action, 0) < 2)


def attempt(npc, context, action='interact'):
    attempts = npc.setdefault('action_attempts', {}).setdefault(context, {})
    attempts[action] = attempts.get(action, 0) + 1


def close_interaction(npc):
    classify(npc)
    if npc.get('outcome') in RESOLVED_OUTCOMES:
        return
    if npc.get('category') in {'obstacle', 'item', 'resource'}:
        npc.update(status='pending', outcome='unresolved')
    else:
        npc.update(status='talked', outcome='conversed')


def manual_target(data, state, key):
    steps = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
    delta = steps.get(getattr(state, 'player_facing', None))
    if delta:
        cell = [state.x+delta[0], state.y+delta[1]]
        matches = [n for n in data['npcs'].values() if n['map'] == key
                   and n['cell'] == cell and n.get('visible')]
        if len(matches) == 1:
            return matches[0]['id']
    return f'{key}/interaction:{state.x}:{state.y}'


def obstruction_summary(data, map_key=None):
    objects = [n for n in data['npcs'].values() if n.get('outcome') == 'unresolved'
               and (map_key is None or n['map'] == map_key)]
    if objects:
        obj = objects[-1]
        return f"Unresolved {obj.get('category', 'object')} at {obj['cell']}: " + (
            obj.get('last_result') or ' '.join(obj.get('pages', [])[-2:]) or 'No confirmed response')
    return 'No untried reachable objects or exploration frontiers'
