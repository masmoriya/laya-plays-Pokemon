"""Transition budgets persist across planner resets; novel evidence releases them."""


def evidence(memory):
    data = memory.world.get('journey_strategy', {})
    return (memory.world.get('discovery_revision', 0), len(data.get('clues', ())),
            sum(n.get('outcome') in {'collected', 'defeated', 'moved', 'conversed'}
                for n in data.get('npcs', {}).values()),
            tuple(memory.world.get('route', {}).get('completed', ())))


def counts(memory):
    # New camera tiles and dialogue fragments do not justify another cave lap.
    from .progress_contract import progress_stamp
    stamp = progress_stamp(memory)
    data = memory.world.setdefault('transition_budget', {})
    if data.get('evidence') != stamp:
        data.update(evidence=stamp, counts={}, portals={})
    return data.setdefault('counts', {})


def transition_key(map_key, cell, destination):
    return f'{map_key}:{tuple(cell)}'


def record_transition(memory, source, cell, destination):
    visits = counts(memory)
    key = transition_key(source, cell, destination)
    visits[key] = visits.get(key, 0) + 1
    memory.world['transition_budget'].setdefault('portals', {})[key] = {
        'map': source, 'kind': 'exit', 'cell': list(cell), 'destination_key': destination}
    memory.save()


def filter_cycles(targets, memory):
    visits = counts(memory)
    from .navigation_memory import same_approach
    portals = memory.world['transition_budget'].get('portals', {})
    def attempts(target):
        key = transition_key(target['map'], target['cell'], target.get('destination_key', ''))
        return sum(count for stamp, count in visits.items()
                   if stamp == key or (stamp in portals and same_approach(
                       target, portals[stamp], 'Repeated map cycle')))
    return [t for t in targets if t['kind'] != 'exit'
            or t.get('retreat_reason') or attempts(t) < 3]
