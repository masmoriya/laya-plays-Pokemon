"""Relevant navigation evidence, durable exclusions, and compact model memory."""
import hashlib
import json

from ..route_progress import MAIN


def evidence_stamp(memory, goal, map_key):
    from .journey_context import objective_clues
    data = memory.world.get('journey_strategy', {})
    clues = objective_clues(data.get('clues', []), MAIN.get(goal, ''))
    blockers = ('door', 'gate', 'blocked', 'unlocked', 'cleared', 'slowpoke', 'bridge')
    clues += [c for c in data.get('clues', [])
              if any(word in c['text'].casefold() for word in blockers)]
    value = {'goal': goal, 'completed': memory.world.get('route', {}).get('completed', []),
             'clues': sorted({c['text'] for c in clues if c.get('map') == map_key}),
             'capabilities': memory.world.get('navigation_capabilities', [])}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def failed_target(item):
    try:
        area, kind, cell, direction, destination = json.loads(item['target_key'])
        return dict(map=area, kind=kind, cell=cell, direction=direction,
                    destination_key=destination, id=item['target'])
    except (KeyError, ValueError, TypeError):
        return {'id': item.get('target')}


def same_approach(target, failed, reason):
    from .experience import target_key
    if (failed.get('kind') == 'explore' and target.get('id') == failed.get('id')
            and (target.get('reobserve_interaction') or target.get('kind') == 'talk')):
        # A different camera approach is not new evidence that the same
        # last-seen person is present. Experience.failures releases this only
        # after that identity is observed again.
        return True
    if (target.get('kind') == failed.get('kind') == 'exit'
            and target.get('map') == failed.get('map')
            and target.get('cell') == failed.get('cell')
            and target.get('direction', '') == failed.get('direction', '')):
        return True
    if (target.get('id') is not None and target.get('id') == failed.get('id')) or target_key(target) == target_key(failed):
        return True
    # A transition budget groups adjacent tiles at one physical portal, while
    # a persisted failed approach must not suppress neighboring exits.
    if 'cycle' not in reason.lower() and 'repeated movement' not in reason.lower():
        return False
    a, b = target.get('cell'), failed.get('cell')
    return (target.get('kind') == failed.get('kind') == 'exit'
            and target.get('map') == failed.get('map')
            and target.get('destination_key') not in (None, '00:00')
            and target.get('destination_key') == failed.get('destination_key')
            and a is not None and b is not None
            and abs(a[0]-b[0]) + abs(a[1]-b[1]) <= 1)


def allowed_targets(memory, goal, targets, *, preserve_cycles_to=None):
    failures = memory.experience.failures(goal)
    return [target for target in targets if not any(
        not (preserve_cycles_to and target.get('kind') == 'exit'
             and target.get('destination_key') == preserve_cycles_to
             and ('cycle' in item['reason'].casefold()
                  or 'repeated movement' in item['reason'].casefold()))
        and
        same_approach(target, failed_target(item), item['reason'])
        and (item.get('evidence_stamp') == evidence_stamp(memory, goal, item.get('map'))
             if item.get('evidence_stamp') is not None
             else item.get('goal') == goal)
        for item in failures)]


def navigation_memory(strategy, state, targets=None):
    """Small enough for Laya; full evidence remains in the notebook."""
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    failures = [f for f in strategy.owner.memory.experience.failures(strategy.owner.route.now)
                if f.get('map') == key]
    failures.sort(key=lambda f: f.get('timestamp', 0), reverse=True)
    rows = strategy.owner.memory.experience.recent(80)
    actions = {r['id']: r for r in rows if r['kind'] == 'action'}
    recent = []
    for row in rows:
        action = actions.get(row.get('decision_id'))
        if row['kind'] != 'outcome' or not action:
            continue
        if action.get('goal') != strategy.owner.route.now:
            continue
        if action.get('before', {}).get('map') != [state.map_group, state.map_number]:
            continue
        recent.append(f"{action['action']}: {row['outcome'][:72]}")
        if len(recent) == 2:
            break
    leads = [n for n in strategy.data['npcs'].values() if n.get('map') == key
             and n.get('status') == 'pending' and n.get('outcome') not in ('collected', 'defeated')]
    targets = targets if targets is not None else (strategy.payload or {}).get('candidates', [])
    exits = [t for t in targets if t.get('map') == key and t.get('kind') in ('exit', 'explore')]
    exits = allowed_targets(strategy.owner.memory, strategy.owner.route.now, exits)
    unresolved = [f"{t['id']} at {t['cell']}" for t in exits[:1]]
    unresolved += [f"{n['id']} at {n['cell']}" for n in leads[:2-len(unresolved)]]
    target = strategy.target or {}
    approach = {key: target[key] for key in
                ('kind', 'cell', 'direction', 'destination_key', 'reentry') if key in target}
    return {'objective': strategy.owner.route.now, 'arrived_from': strategy.arrived_from,
            'approach': approach,
            'failed': [f"{f['target']}: {f['reason'][:72]}" for f in failures[:2]],
            'recent': recent,
            'unresolved': unresolved}


def target_evidence(target, memory):
    """Describe provenance without upgrading guessed destinations to facts."""
    destination = target.get('destination_key')
    if target.get('kind') != 'exit':
        return 'observed local lead'
    if destination in (None, '00:00'):
        return 'observed exit; destination unknown'
    if any(c['from'] == target['map'] and c['to'] == destination
           and c['at'] == target['cell']
           for c in memory.world['journey_strategy']['connections']):
        return 'observed traversal'
    return 'map connection; traversal not verified'
