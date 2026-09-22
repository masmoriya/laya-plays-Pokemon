"""Shared priorities and commitment rules for observed navigation tasks."""

COLLECTIBLES = frozenset({'item', 'resource'})


def collectible(target):
    return target.get('category') in COLLECTIBLES and target.get('kind') == 'talk'


def preferred_targets(targets):
    """Do not discard pickups when narrowing a journey to its travel route."""
    forward = [t for t in targets if not t.get('recent_return') or t.get('retreat_reason')]
    if forward:
        targets = forward
    pickups = [t for t in targets if collectible(t)]
    priority_interactions = [t for t in targets if t.get('goal_interaction')
                             and t.get('kind') == 'talk' and not collectible(t)
                             and t.get('journey_reward', 0) > max(
                                 (p.get('journey_reward', 0) for p in pickups), default=0)]
    for predicate in (
        lambda t: t.get('retreat_reason'),
        lambda t: t in priority_interactions,
        collectible,
        lambda t: t.get('travel_route'),
        lambda t: t.get('investigation_priority'),
        lambda t: t.get('goal_interaction'),
    ):
        preferred = [target for target in targets if predicate(target)]
        if preferred:
            if all(collectible(t) and 'path_steps' in t for t in preferred):
                distance = min(t['path_steps'] for t in preferred)
                return [t for t in preferred if t['path_steps'] == distance]
            return preferred
    return targets


def preserves_commitment(active, proposed, state, memory, terrain):
    """Background advice cannot turn a valid, committed route into a zigzag."""
    if not active or active['id'] == proposed['id']:
        return False
    if proposed.get('retreat_reason') or (collectible(proposed) and not collectible(active)):
        return False
    from .journey_targets import target_options
    return bool(target_options(active, state, memory, terrain))


def prefer_discovery(targets, memory):
    """Suppress incidental returns when a reachable new destination exists."""
    known = {key for key, area in memory.world['maps'].items() if area.get('visited')}
    for connection in memory.world['journey_strategy']['connections']:
        known.update((connection['from'], connection['to']))
    for target in targets:
        if target.get('destination_key'):
            target['unvisited_destination'] = target['destination_key'] not in known
    novel = [target for target in targets if target.get('unvisited_destination')]
    if not novel:
        return targets
    # Preserve Journey reward order; novelty only breaks equal-reward ties.
    novel_ids = {target['id'] for target in novel}
    return sorted(targets, key=lambda target: (
        -target.get('journey_reward', 0), target['id'] not in novel_ids))
