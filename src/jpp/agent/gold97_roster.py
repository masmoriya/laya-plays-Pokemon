"""Roster selection preserves field coverage and a strong battler before rotation."""
from .gold97_mechanics import types, move_info, multiplier

FIELD_MOVES = frozenset(('CUT','SURF','STRENGTH','FLASH','FLY','WATERFALL','WHIRLPOOL'))


def roster_plan(state, opponent=None, required_move=None):
    if not state.mechanics_verified or not state.storage_verified or not state.box_roster:
        return None
    party, boxed = list(state.party), list(state.box_roster)
    all_mons = party + boxed
    keys = [m.identity for m in all_mons]
    if None in keys or len(keys) != len(set(keys)):
        return None
    healthy = [m for m in party if m.hp > 0 and any(m.pp)]
    if not healthy:
        return None
    selected = [max(healthy, key=lambda m: (m.level, m.hp))]
    needed = set().union(*(set(move.upper() for move in m.moves) & FIELD_MOVES for m in party))
    while len(selected) < min(6, len(all_mons)):
        covered = set().union(*(set(types(m)) for m in selected))
        fields = set().union(*(set(move.upper() for move in m.moves) for m in selected))
        candidates = [m for m in all_mons if m not in selected]
        def score(mon):
            from .hm_preparation import compatible
            moves = {move.upper() for move in mon.moves}
            # Preserve required field users, then coverage; retain ties in party.
            matchup = max((multiplier(info['type'], types(opponent))
                           for name in mon.moves if (info := move_info(name)) and info['power']), default=0) if opponent else 0
            missing_hm = required_move and not any(compatible(m, required_move) for m in selected)
            return (bool(missing_hm and compatible(mon, required_move)),
                    len((needed - fields) & moves), matchup, len(set(types(mon)) - covered),
                    mon.level, mon in party)
        selected.append(max(candidates, key=score))
    # Keep an existing healthy trainee when the final slot is otherwise redundant.
    trainee = min(healthy, key=lambda m: m.level)
    if trainee not in selected and trainee.level < selected[0].level:
        last = selected[-1]
        other_fields = set().union(*({v.upper() for v in m.moves} for m in selected[:-1]))
        from .hm_preparation import compatible
        preserves_hm = not required_move or any(compatible(m, required_move) for m in selected[:-1] + [trainee])
        if needed <= other_fields and preserves_hm:
            selected[-1] = trainee
    desired = {m.identity for m in selected}
    incoming = next((m for m in selected if m in boxed), None)
    if incoming is None:
        return None
    if len(party) < 6:
        return {'kind': 'withdraw', 'identity': incoming.identity, 'box': incoming.storage_box}
    outgoing = next((m for m in reversed(party) if m.identity not in desired), None)
    if outgoing is None or sum(m.hp > 0 for m in party if m is not outgoing) == 0:
        return None
    boxes = [state.current_box] + [i for i in range(14) if i != state.current_box]
    available = next((i for i in boxes if sum(m.storage_box == i for m in boxed) < 20), None)
    return {'kind': 'deposit', 'identity': outgoing.identity, 'box': available} if available is not None else None
