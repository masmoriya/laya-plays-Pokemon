"""User-enabled training favors experience over preserving journey reserves."""
from math import ceil

from .gold97_battle import BattleAction
from .gold97_damage import attacks, incoming
from .gold97_readiness import usable_attacks


def viable(mon, foe, *, switching=False):
    """Allow spending HP, but require a credible win including switch damage."""
    if mon.hp <= 0 or mon.status != 'none' or not usable_attacks(mon):
        return False
    damage = [e for _, e in attacks(mon, foe) if e.known and e.expected > 0]
    risk = incoming(foe, mon)
    if damage and risk:
        turns = ceil(foe.hp / max(e.expected for e in damage))
        return (mon.hp > risk.high * (turns + int(switching))
                and sum(pp for _, pp in usable_attacks(mon)) >= turns)
    # Unknown stats still need a level advantage and a nonimmune attack.
    return (any(e.high > 0 for _, e in attacks(mon, foe))
            and mon.level >= foe.level + 3 + int(switching)
            and mon.hp_fraction > .5)


def practice_action(strategy, state):
    active, foe = state.battle.active, state.battle.opponent
    participants = getattr(state, 'battle_participants', None)
    choices = []
    for i, mon in enumerate(state.party):
        current = i == state.active_slot
        mon = active if current else mon
        if not current and (getattr(state, 'switch_allowed', None) is False
                            or i in strategy.switched_from):
            continue
        if viable(mon, foe, switching=not current):
            # Once someone has entered for XP, let a viable active partner finish.
            already_shared = participants is not None and participants.bit_count() > 1
            choices.append((0 if current and already_shared else 1, mon.level,
                            0 if current else 1, i))
    if not choices:
        return BattleAction('escape', reason='Training: recover before the next fight')
    target = min(choices)[-1]
    if target != state.active_slot:
        return BattleAction('switch', target, 'Training: use a suitable lower-level partner')
    return strategy.attack(active, foe)
