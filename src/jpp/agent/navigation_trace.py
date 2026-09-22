"""Observed movements and bounded target retries, independent of planner resets."""
import json
from .exploration_cycles import evidence


def progress_trace(memory):
    data = memory.world.setdefault('navigation_trace', {})
    stamp = repr(evidence(memory))
    if data.get('evidence') != stamp:
        data.update(evidence=stamp, edges={}, targets={})
    return data


def edge_key(origin, direction):
    return json.dumps([list(origin), direction])


def record_step(memory, key, origin, destination):
    dx, dy = destination[0]-origin[0], destination[1]-origin[1]
    direction = {(0,-1):'up', (0,1):'down', (-1,0):'left', (1,0):'right'}.get((dx,dy))
    if direction is None:
        return
    area = memory.map(key)
    trail = area.setdefault('trail', [])
    if not trail:
        trail.append(list(origin))
    trail.append(list(destination))
    del trail[:-64]
    stamp = edge_key(origin, direction)
    totals = area.setdefault('movement_counts', {})
    totals[stamp] = totals.get(stamp, 0) + 1
    recent = progress_trace(memory)['edges'].setdefault(key, {})
    recent[stamp] = recent.get(stamp, 0) + 1
    memory.save()


def edge_costs(memory, key):
    return tuple(sorted(progress_trace(memory)['edges'].get(key, {}).items()))


def target_stamp(target):
    return json.dumps([target.get('map'), target['kind'], target.get('cell'), target.get('direction', '')])


def record_target(memory, target):
    if target['kind'] not in {'explore', 'exit'}:
        return
    counts = progress_trace(memory)['targets']
    stamp = target_stamp(target)
    counts[stamp] = counts.get(stamp, 0) + 1
    memory.save()


def unexhausted(memory, targets):
    counts = progress_trace(memory)['targets']
    return [t for t in targets if t.get('prerequisite') or t.get('retreat_reason')
            or counts.get(target_stamp(t), 0) < 2]
