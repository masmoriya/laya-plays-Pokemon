"""One encounter policy; safety gates precede collection and training rewards."""
from .gold97_battle import BattleAction
from .gold97_damage import attacks, incoming, estimate
from math import ceil
from .gold97_mechanics import move_info, multiplier, types
from .gold97_services import novel_capture
from .gold97_readiness import assess_party, affordable_fight


def capture_eligible(strategy, state, foe):
    """Require current ownership evidence for every capture path."""
    species_id = getattr(foe, 'species_id', None)
    caught = set(getattr(state, 'pokedex_caught_ids', ()) or ())
    party = {getattr(mon, 'species_id', None)
             for mon in getattr(state, 'party', ()) or ()}
    if species_id is None or species_id in caught or species_id in party:
        return False
    return (novel_capture(state, foe)
            or getattr(strategy, 'static_capture', False))


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


def encounter_action(strategy, state, *, intent='travel', readiness=None):
    active, foe = state.battle.active, state.battle.opponent
    if active is None or foe is None:
        return BattleAction('wait', reason='Waiting for encounter state')
    if active.hp <= 0:
        return strategy.combat_plan(state, forced=True)
    # A failed escape roll or forced replacement does not forbid another RUN.
    if getattr(state, 'escape_allowed', None) is False:
        return strategy.combat_plan(state)
    if intent == 'practice':
        from .training_encounters import practice_action
        return practice_action(strategy, state)
    readiness = readiness or assess_party(state, threats=(foe,))
    if readiness.conserve or readiness.needs_detour:
        return BattleAction('escape', reason='Run to preserve the team')
    safe = [i for i in readiness.capable_slots
            if affordable_fight(active if i == state.active_slot else state.party[i], foe,
                                switching=i != state.active_slot)]
    if not safe:
        return BattleAction('escape', reason='Run: battle cost threatens journey reserves')
    if state.active_slot not in safe:
        backup = max(safe, key=lambda i: (state.party[i].level, state.party[i].hp))
        return BattleAction('switch', backup, 'Switch: safe fight preserves reserves')
    risk = incoming(foe, active)
    backup = replacement(state)
    if not any(active.pp) or active.hp_fraction <= .25 or (risk and active.hp <= risk.high):
        if backup is not None:
            return BattleAction('switch', backup, 'Switch: keep a viable battler')
        return BattleAction('escape', reason='Escape: insufficient health or attacks')
    eligible = capture_eligible(strategy, state, foe)
    balls = getattr(state, 'poke_ball_count', None)
    if (eligible and balls and getattr(strategy, 'capture_attempts', 0) < 3
            and affordable_fight(active, foe, extra_turns=2)):
        # Unknown retaliation does not justify spending a turn on weakening.
        preparation = capture_move(active, foe) if risk and active.hp > risk.high * 2 else None
        return preparation or BattleAction('ball', reason=f'Capture {foe.species.title()}')
    if intent == 'training' and backup in safe and training_handoff(strategy, state, backup):
        return BattleAction('switch', backup, f'Train {active.species.title()}: let the stronger partner finish')
    if not any(e.high > 0 for _, e in attacks(active, foe)):
        return BattleAction('escape', reason='Escape: no verified effective attack')
    action = strategy.combat_plan(state)
    if action.kind == 'switch' and action.target not in safe:
        return strategy.attack(active, foe)
    return action


def training_handoff(strategy, state, backup):
    """A baby lead gets one safe handoff; capable battlers keep attacking."""
    active, foe = state.battle.active, state.battle.opponent
    if (backup is None or strategy.switched_from or not 0 < active.level < 10
            or str(active.held_item).upper() == 'EXP SHARE'
            or state.party[backup].level < active.level + 3):
        return False
    participants = getattr(state, 'battle_participants', None)
    slot = getattr(state, 'active_slot', None)
    if participants is not None and (slot is None or participants & ~(1 << slot)):
        return False
    best = max((e.expected for _, e in attacks(active, foe) if e.known), default=0)
    risk = incoming(foe, active)
    turns = ceil(foe.hp / best) if best > 0 else None
    return not (turns is not None and turns <= 2 and risk is not None
                and active.hp > risk.high * turns)
