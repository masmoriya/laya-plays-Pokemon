"""Small, cartridge-safe battle strategy for Gold 97.

The tactical provider is useful for route choices, but battle mechanics need a
local guard: a model (or a stale menu cursor) must never confirm a move whose PP
is already zero.  This planner keeps the choice deterministic and explainable.
"""

from .. import facts, gamedata
from .gold97_move_data import MOVE_OVERRIDES


from dataclasses import dataclass
from math import ceil
from .gold97_mechanics import move_info, multiplier, REFERENCE
from .gold97_damage import attacks, estimate, incoming, acts_first


_GOLD97_MOVE_ALIASES = {"PSYCHIC M": "PSYCHIC"}


def _move_name(name):
    return str(name or "").replace("-", " ").replace("_", " ").upper()


def _type_multiplier(attack_type, defender_types):
    return multiplier(str(attack_type).upper(), tuple(str(t).upper() for t in defender_types))


def _move_data(name):
    """Return normalized move data, tolerating cartridge punctuation."""
    normalized = _move_name(name)
    info = move_info(normalized)
    if info:
        return normalized, info['type'], info['power'], info['pp']
    lookup_name = _GOLD97_MOVE_ALIASES.get(normalized, normalized)
    candidates = (lookup_name, lookup_name.replace(" ", "-"),
                  lookup_name.replace(" ", "_"))
    move_id = None
    for candidate in candidates:
        move_id = facts.move_id(candidate)
        if move_id is not None:
            break
    override = MOVE_OVERRIDES.get(normalized)
    if move_id is None:
        return (normalized, override[0] if override else "NORMAL",
                override[1] if override else None, 0)
    _, generic_type, generic_power, max_pp = gamedata.move(move_id)
    return (normalized, override[0] if override else generic_type,
            override[1] if override else generic_power, max_pp)


@dataclass(frozen=True)
class BattleAction:
    kind: str
    target: int | None = None
    reason: str = ""


class Gold97BattleStrategy:
    """Pure turn planning: repeated observations cannot consume setup or turns."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.capture_attempts = 0
        self.static_capture = False
        self.switched_from = set()

    def record_switch(self, previous_slot):
        """Only confirmed entries consume a handoff, never repeated planning."""
        if previous_slot is not None:
            self.switched_from.add(previous_slot)

    def choose(self, active, opponent=None):
        return self.attack(active, opponent).target

    def attack(self, active, opponent):
        legal = attacks(active, opponent)
        if not legal:
            return BattleAction('struggle', reason='No PP left: use Struggle')
        hp = getattr(opponent, 'hp', None)
        damaging = [(i, e) for i, e in legal if e.high > 0]
        if not damaging:
            return BattleAction('move', legal[0][0], 'No effective attack available')
        def rank(pair):
            i, e = pair
            knockout = bool(hp and e.bounded and e.low >= hp)
            return (knockout and e.accuracy >= .95, e.accuracy if knockout else 0,
                    min(hp, e.expected) if hp and e.known else e.expected, -i)
        index, best = max(damaging, key=rank)
        threat = incoming(opponent, active)
        # Defense reduction pays off only when the *whole* sequence is shorter
        # and the user can survive the extra turn. Unknown stats never justify it.
        if hp and best.bounded and best.low < hp and threat and threat.bounded:
            for i, _ in legal:
                info = move_info(active.moves[i])
                if not info or info['effect'] not in {'DEFENSE_DOWN', 'DEFENSE_DOWN_2'}:
                    continue
                lowered = estimate(active, opponent, active.moves[index],
                                   defense_stage_delta=-2 if info['effect'].endswith('_2') else -1)
                direct = ceil(hp / max(1, best.expected))
                setup = 255 / max(1, info['accuracy_byte']) + ceil(hp / max(1, lowered.expected))
                if setup < direct and getattr(active, 'hp', 0) > threat.high * setup:
                    return BattleAction('move', i, 'Setup saves turns and survives retaliation')
        reason = 'Attack: likely knockout' if hp and best.bounded and best.low >= hp else 'Attack: best nominal damage; modifiers uncertain'
        return BattleAction('move', index, reason)

    def plan(self, state, *, optional=False, forced=False, intent='travel', readiness=None):
        if state.battle.kind == 'wild' and not optional and not forced:
            from .gold97_encounters import encounter_action
            return encounter_action(self, state, intent=intent, readiness=readiness)
        return self.combat_plan(state, optional=optional, forced=forced)

    def combat_plan(self, state, *, optional=False, forced=False):
        active, foe = state.battle.active, state.battle.opponent
        if active is None:
            party = tuple(getattr(state, 'party', ()) or ())
            slot = getattr(state, 'active_slot', None)
            active = (party[slot] if slot is not None and 0 <= slot < len(party)
                      else next((mon for mon in party if getattr(mon, 'hp', 0) > 0), None)
                      if party else None)
        if optional:
            foe = getattr(state, 'upcoming_opponent', None)
            if foe is None:
                return BattleAction('stay', reason='Stay in: next opponent is not yet verified')
        if active is None:
            return BattleAction('wait', reason='Waiting for readable battle state')
        current = getattr(state, 'active_slot', None)
        if current is None and getattr(active, 'slot', 0):
            current = active.slot - 1
        candidates = [(i, mon) for i, mon in enumerate(getattr(state, 'party', ()))
                      if i != current and mon.hp > 0 and mon is not active
                      and (current is not None or getattr(active, 'hp', 0) == 0)]
        def value(mon):
            damage = max((e.expected for _, e in attacks(mon, foe)), default=0)
            risk = incoming(foe, mon)
            return (mon.hp > (risk.high if risk else 0), damage, mon.hp)
        replacement = max(candidates, key=lambda item: value(item[1]), default=None)
        if forced or active.hp <= 0:
            return (BattleAction('switch', replacement[0], 'Switch: healthy replacement') if replacement
                    else BattleAction('wait', reason='No verified healthy replacement'))
        if getattr(state, 'switch_allowed', None) is False:
            replacement = None
        attack = self.attack(active, foe)
        threat = incoming(foe, active)
        if optional:
            if replacement and threat and value(replacement[1]) > value(active) and (
                    active.hp <= threat.high or value(replacement[1])[1] > value(active)[1] * 1.5):
                return BattleAction('switch', replacement[0], 'Switch: safer matchup')
            return BattleAction('stay', reason='Stay in: no clear switching benefit')
        chosen = estimate(active, foe, active.moves[attack.target]) if attack.target is not None else None
        faster = attack.target is not None and acts_first(active, foe, active.moves[attack.target])
        if chosen and chosen.bounded and chosen.low >= getattr(foe, 'hp', 1) and chosen.accuracy >= .95 and faster:
            return attack
        if (replacement and replacement[0] not in self.switched_from
                and chosen and chosen.known and getattr(foe, 'hp', 0) > 0):
            bench = replacement[1]
            stronger = max((e for _, e in attacks(bench, foe) if e.known),
                           key=lambda e: e.expected, default=None)
            risk = incoming(foe, bench)
            if stronger and risk and stronger.expected > chosen.expected * 1.5:
                switch_turns = 1 + ceil(foe.hp / max(1, stronger.expected))
                stay_turns = ceil(foe.hp / max(1, chosen.expected))
                if switch_turns < stay_turns and bench.hp > risk.high * switch_turns:
                    return BattleAction('switch', replacement[0],
                                        'Switch: stronger matchup saves turns after entry cost')
        if threat and active.hp <= threat.high:
            if replacement:
                risk = incoming(foe, replacement[1])
                if risk and replacement[1].hp > risk.high * 2:
                    return BattleAction('switch', replacement[0], 'Switch: survive incoming attack')
            healed = min(active.max_hp, active.hp + REFERENCE['items']['POTION']['heal_hp'])
            if current is not None and getattr(state, 'potion_count', 0) > 0 and healed > threat.high * 2:
                return BattleAction('heal', current, 'Heal: survive retaliation')
        from .gold97_sacrifice import sacrifice_line
        sacrifice = sacrifice_line(state, attack)
        return sacrifice or attack
