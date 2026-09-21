"""One encounter policy; safety gates precede collection and training rewards."""
from .gold97_battle import BattleAction
from .gold97_damage import attacks, incoming, estimate
from .gold97_mechanics import move_info, multiplier, types
from .gold97_services import novel_capture


def healthy(mon):
    return mon.hp > 0 and mon.hp_fraction > .5 and mon.status == 'none' and any(mon.pp)


def replacement(state):
    foe = state.battle.opponent
    choices = []
    for index, mon in enumerate(state.party):
        risk = incoming(foe, mon)
        damage = max((e.expected for _, e in attacks(mon, foe) if e.known), default=0)
        if index != state.active_slot and healthy(mon) and risk and mon.hp > risk.high * 2 and damage:
            choices.append((damage, mon.hp, index))
    return max(choices)[2] if choices else None


def capture_move(active, foe):
    if foe.status == 'none':
        for index, name in enumerate(active.moves):
            info = move_info(name)
            if (index < len(active.pp) and active.pp[index] and info and
                    info['effect'] in {'SLEEP', 'PARALYZE'} and
                    multiplier(info['type'], types(foe)) > 0):
                return BattleAction('move', index, 'Capture: apply status before throwing')
    if foe.hp_fraction <= .35:
        return None
    safe = []
    for index, damage in attacks(active, foe):
        info = move_info(active.moves[index])
        # A critical hit can exceed the nominal range. False Swipe is capped.
        ceiling = damage.high * (1 if info and info['effect'] == 'FALSE_SWIPE' else 2)
        if damage.known and damage.high > 0 and ceiling < foe.hp and damage.turns == 1:
            safe.append((damage.expected, index))
    if safe:
        return BattleAction('move', max(safe)[1], 'Capture: weaken without a predicted knockout')
    return None


def encounter_action(strategy, state):
    active, foe = state.battle.active, state.battle.opponent
    if active is None or foe is None:
        return BattleAction('wait', reason='Waiting for encounter state')
    if active.hp <= 0:
        return strategy.combat_plan(state, forced=True)
    risk = incoming(foe, active)
    backup = replacement(state)
    if not any(active.pp) or active.hp_fraction <= .25 or (risk and active.hp <= risk.high):
        if backup is not None:
            return BattleAction('switch', backup, 'Switch: keep a viable battler')
        return BattleAction('escape', reason='Escape: insufficient health or attacks')
    eligible = novel_capture(state, foe) or getattr(strategy, 'static_capture', False)
    balls = getattr(state, 'poke_ball_count', None)
    if eligible and balls and getattr(strategy, 'capture_attempts', 0) < 3:
        # Unknown retaliation does not justify spending a turn on weakening.
        preparation = capture_move(active, foe) if risk and active.hp > risk.high * 2 else None
        return preparation or BattleAction('ball', reason=f'Capture {foe.species.title()}')
    if (backup is not None and str(active.held_item).upper() != 'EXP SHARE' and
            state.party[backup].level >= active.level + 3):
        return BattleAction('switch', backup, f'Train {active.species.title()}: let the stronger partner finish')
    if not any(e.high > 0 for _, e in attacks(active, foe)):
        return BattleAction('escape', reason='Escape: no verified effective attack')
    return strategy.combat_plan(state)
