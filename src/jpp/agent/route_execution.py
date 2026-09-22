"""Continue an accepted route only while the next observed step is safe."""
from copy import copy
from .journey_targets import target_options
from .gold97_navigation import STEPS


def committed_heading(owner, state, direction):
    strategy = owner.strategy
    target = strategy.target
    if (owner.paused or state.in_battle or not target or (strategy.future and not strategy.shared_control)
            or strategy.observations.pending or owner.terrain is None
            or direction not in STEPS or target['map'] != f'{state.map_group:02X}:{state.map_number:02X}'):
        return False
    # The map coordinate updates at the end of a step. By then fast-forward
    # may already have queued another step. Release during the animation when
    # its native destination is the target or the next turn in the route.
    destination = getattr(state, 'player_next_position', None)
    if getattr(state, 'player_moving', False):
        if destination is None:
            return False
        state = copy(state)
        object.__setattr__(state, 'x', destination[0])
        object.__setattr__(state, 'y', destination[1])
    if tuple(target['cell']) == (state.x, state.y):
        return False
    from .navigation_policy import collectible, preferred_targets, COLLECTIBLES
    from .object_memory import RESOLVED_OUTCOMES
    if (not collectible(target) and not target.get('retreat_reason')
            and any(obj['map'] == target['map'] and obj.get('category') in COLLECTIBLES
                    and obj.get('outcome') not in RESOLVED_OUTCOMES
                    for obj in strategy.data['npcs'].values())):
        from .journey_targets import candidates
        leads = preferred_targets(candidates(state, owner.memory, owner.terrain,
                                              excluded=strategy.excluded,
                                              reward_weights=owner.rewards.weights))
        if any(collectible(lead) for lead in leads):
            return False  # Reconsider before a held direction walks past a pickup.
    dx, dy = STEPS[direction]
    next_cell = state.x+dx, state.y+dy
    # Stop before a visible/remembered object or warp; the normal executor owns
    # turning, interaction, and map transitions.
    for obj in strategy.data['npcs'].values():
        if (obj['map'] == target['map'] and tuple(obj['cell']) == next_cell
                and obj.get('outcome') != 'collected'):
            return False
    if any(tuple(e[:2]) == next_cell for e in getattr(owner.terrain, 'exits', ())):
        return False
    return set(target_options(target, state, owner.memory, owner.terrain)) == {direction}
