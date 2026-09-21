"""A deliberate faint requires a verified, better follow-up line."""
from .gold97_damage import estimate, incoming, acts_first, attacks
from .gold97_battle import BattleAction


def sacrifice_line(state, attack):
    active, foe = state.battle.active, state.battle.opponent
    if state.battle.kind != 'trainer' or active is None or foe is None or attack.target is None:
        return None
    if any(not hit.known for _, hit in attacks(foe, active)):
        return None
    threat = incoming(foe, active)
    damage = estimate(active, foe, active.moves[attack.target])
    if (not threat or active.hp > threat.low or not damage.known or damage.accuracy < .95
            or not acts_first(active, foe, active.moves[attack.target])):
        return None
    for i, mon in enumerate(state.party):
        if i == state.active_slot or mon.hp <= 0:
            continue
        risk = incoming(foe, mon)
        if not risk:
            continue
        for slot, hit in attacks(mon, foe):
            if (hit.known and hit.accuracy >= .95 and hit.low >= foe.hp - damage.low
                    and acts_first(mon, foe, mon.moves[slot]) and mon.hp <= risk.low
                    and damage.low < foe.hp):
                # Switching loses this finisher to the conceded attack. Staying
                # attacks first, then permits its free entry after the faint.
                return BattleAction('move', attack.target,
                                    'Tactical sacrifice: damage enables a safe finishing attack')
    return None
