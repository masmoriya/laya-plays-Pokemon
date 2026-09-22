"""Shared journey reserves and conservative optional-battle budgets."""
from dataclasses import dataclass
from math import ceil

from .gold97_damage import attacks, incoming
from .gold97_mechanics import move_info


def usable_attacks(mon):
    return [(name, pp) for name, pp in zip(getattr(mon, 'moves', ()), getattr(mon, 'pp', ()))
            if pp > 0 and (info := move_info(name))
            and (info['power'] > 0 or info['effect'] == 'OHKO')]


def hp_fraction(mon):
    return getattr(mon, 'hp', 0) / max(1, getattr(mon, 'max_hp', 0))


def capable(mon, foe=None):
    if (getattr(mon, 'species', '') == 'EGG' or hp_fraction(mon) <= .5
            or getattr(mon, 'status', 'none') != 'none' or not usable_attacks(mon)):
        return False
    if foe is None:
        return True
    damage = [e for _, e in attacks(mon, foe) if e.known and e.high > 0]
    risk = incoming(foe, mon)
    if risk and damage:
        turns = ceil(foe.hp / max(e.expected for e in damage))
        return mon.hp > risk.high * max(2, turns)
    # Immunity is evidence even when stats or enemy moves are unavailable.
    if not any(e.high > 0 for _, e in attacks(mon, foe)):
        return False
    level = getattr(foe, 'level', None)
    return level is not None and getattr(mon, 'level', 0) >= ceil(level * .8)


@dataclass(frozen=True)
class Readiness:
    capable_slots: tuple[int, ...]
    lead: int | None
    needs_detour: bool
    conserve: bool
    reason: str


def assess_party(state, *, threats=(), required=None):
    party = tuple(getattr(state, 'party', ()) or ())
    # Battle RAM is fresher than party RAM for the active combatant.
    active = getattr(getattr(state, 'battle', None), 'active', None)
    slot = getattr(state, 'active_slot', None)
    if getattr(state, 'in_battle', False) and active is not None and slot is not None:
        party = tuple(active if i == slot else mon for i, mon in enumerate(party))
    threats = tuple(foe for foe in threats if foe is not None)
    current = getattr(getattr(state, 'battle', None), 'opponent', None)
    fighting = getattr(state, 'in_battle', False) and current is not None
    capable_slots = tuple(i for i, mon in enumerate(party)
                          if capable(mon) and (capable(mon, current) if fighting else
                             not threats or any(capable(mon, foe) for foe in threats)))
    # Different partners can cover different matchups; no one partner has to
    # defeat every local species alone.
    covered = all(any(capable(mon, foe) for mon in party) for foe in threats)
    required_ready = required is None or any(capable(mon, required) for mon in party)
    detour = bool(party) and (not capable_slots or not covered or not required_ready)
    lead = max(capable_slots, key=lambda i: (getattr(party[i], 'level', 0), hp_fraction(party[i])), default=None)
    reason = ('Return to heal; insufficient battle reserves' if detour else
              'Conserve the remaining capable partner' if len(capable_slots) == 1 else
              'Continue; capable partners remain')
    return Readiness(capable_slots, lead, detour, len(capable_slots) < 2, reason)


def affordable_fight(mon, foe, *, switching=False, extra_turns=0):
    """Budget a switch, retaliation, and a spare hit; estimates are not guarantees."""
    if not capable(mon, foe):
        return False
    damage = [e for _, e in attacks(mon, foe) if e.known and e.expected > 0]
    risk = incoming(foe, mon)
    if damage and risk:
        turns = ceil(foe.hp / max(e.expected for e in damage))
        cost = turns + int(switching) + extra_turns
        return (sum(pp for _, pp in usable_attacks(mon)) > turns
                and mon.hp - risk.high * cost > max(mon.max_hp * .5, risk.high))
    # Missing stats are not proof of cheap combat. Only accept a substantial
    # level/resource advantage, with a larger margin when switching or catching.
    return (mon.level >= foe.level + 3 + 2 * (int(switching) + extra_turns)
            and mon.hp_fraction > .75 and sum(pp for _, pp in usable_attacks(mon)) >= 5)
