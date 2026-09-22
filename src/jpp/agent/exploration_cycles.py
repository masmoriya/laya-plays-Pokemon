"""Transition budgets persist across planner resets; novel evidence releases them."""


def evidence(memory):
    data = memory.world.get('journey_strategy', {})
    return (memory.world.get('discovery_revision', 0), len(data.get('clues', ())),
            sum(n.get('outcome') in {'collected', 'defeated', 'moved', 'conversed'}
                for n in data.get('npcs', {}).values()),
            tuple(memory.world.get('route', {}).get('completed', ())))


def counts(memory):
    stamp = repr(evidence(memory))
    data = memory.world.setdefault('transition_budget', {})
    if data.get('evidence') != stamp:
        data.update(evidence=stamp, counts={})
    return data.setdefault('counts', {})


def transition_key(map_key, cell, destination):
    return f'{map_key}:{tuple(cell)}'


def record_transition(memory, source, cell, destination):
    visits = counts(memory)
    key = transition_key(source, cell, destination)
    visits[key] = visits.get(key, 0) + 1
    memory.save()


def filter_cycles(targets, memory):
    visits = counts(memory)
    return [t for t in targets if t['kind'] != 'exit' or t.get('prerequisite')
            or t.get('retreat_reason') or visits.get(transition_key(
                t['map'], t['cell'], t.get('destination_key', '')), 0) < 3]
