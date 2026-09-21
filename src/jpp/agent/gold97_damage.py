"""Conservative damage estimates; unknown mechanics are never guaranteed KOs."""
from dataclasses import dataclass
from .gold97_mechanics import PHYSICAL_TYPES, move_info, multiplier, types


@dataclass(frozen=True)
class Estimate:
    low: int
    high: int
    accuracy: float
    known: bool
    turns: int = 1

    @property
    def expected(self):
        return (self.low + self.high) / 2 * self.accuracy / self.turns


def stage_factor(stage):
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def stat(mon, index):
    values = getattr(mon, 'stats', ())
    if len(values) != 5 or not all(values):
        return None
    stages = getattr(mon, 'stages', ())
    value = values[index] * stage_factor(stages[index] if len(stages) >= 5 else 0)
    if index == 2 and getattr(mon, 'status', '') == 'paralysis':
        value /= 4
    if index == 0 and getattr(mon, 'status', '') == 'burn':
        value /= 2
    return max(1, int(value))


def estimate(active, foe, name, *, defense_stage_delta=0):
    move = move_info(name)
    if not move:
        return Estimate(0, 0, 0, False)
    effect, power = move['effect'], move['power']
    acc = move['accuracy_byte'] / 255
    stages, enemy_stages = getattr(active, 'stages', ()), getattr(foe, 'stages', ())
    if len(stages) == 7 and len(enemy_stages) == 7:
        acc *= stage_factor(max(-6, min(6, stages[5] - enemy_stages[6])))
    acc = 1.0 if effect == 'ALWAYS_HIT' else min(1.0, acc)
    mult = multiplier(move['type'], types(foe))
    if mult == 0:
        return Estimate(0, 0, acc, True)
    level = getattr(active, 'level', None)
    if effect == 'OHKO':
        enemy_level = getattr(foe, 'level', None)
        if level is None or enemy_level is None or level < enemy_level:
            return Estimate(0, 0, 0, False)
        hp = getattr(foe, 'hp', 0)
        return Estimate(hp, hp, min(1, (30 + level - enemy_level) / 100), True)
    if effect in {'STATIC_DAMAGE', 'LEVEL_DAMAGE'}:
        damage = {'SONICBOOM': 20, 'DRAGON RAGE': 40}.get(move['name'], level)
        return Estimate(damage or 0, damage or 0, acc, damage is not None)
    if effect == 'SUPER_FANG':
        value = max(1, getattr(foe, 'hp', 0) // 2)
        return Estimate(value, value, acc, True)
    if not power:
        return Estimate(0, 0, acc, True)
    # Counter, variable-power and conditional moves need additional observations.
    if power == 1 or effect in {'COUNTER', 'MIRROR_COAT', 'BIDE', 'SELFDESTRUCT'}:
        return Estimate(0, 0, acc, False)
    if effect == 'DREAM_EATER' and getattr(foe, 'status', '') != 'sleep':
        return Estimate(0, 0, acc, True)
    if effect == 'SNORE' and getattr(active, 'status', '') != 'sleep':
        return Estimate(0, 0, acc, True)
    physical = move['type'] in PHYSICAL_TYPES
    attack, defense = stat(active, 0 if physical else 3), stat(foe, 1 if physical else 4)
    if defense and physical and defense_stage_delta:
        old = enemy_stages[1] if len(enemy_stages) >= 5 else 0
        defense = max(1, int(defense * stage_factor(max(-6, old + defense_stage_delta)) / stage_factor(old)))
    stab = 1.5 if move['type'] in types(active) else 1
    known = bool(attack and defense and level and types(foe))
    base = (((2 * level // 5 + 2) * power * attack // defense // 50) + 2
            if known else power)
    high = max(1, int(base * stab * mult))
    low = max(1, high * 217 // 255)
    if effect == 'FALSE_SWIPE':
        high = min(high, max(0, getattr(foe, 'hp', 1) - 1)); low = min(low, high)
    if effect in {'MULTI_HIT', 'DOUBLE_HIT', 'TWINEEDLE'}:
        low *= 2; high *= 5 if effect == 'MULTI_HIT' else 2
    turns = 2 if effect in {'FLY', 'DIG', 'RAZOR_WIND', 'SOLARBEAM', 'SKULL_BASH', 'HYPER_BEAM'} else 1
    return Estimate(low, high, acc, known, turns)


def attacks(mon, foe):
    return [(i, estimate(mon, foe, move)) for i, move in enumerate(getattr(mon, 'moves', ()))
            if i < len(getattr(mon, 'pp', ())) and mon.pp[i] > 0]


def incoming(foe, active):
    known = [value for _, value in attacks(foe, active) if value.known and value.high > 0]
    return max(known, key=lambda value: value.high, default=None)


def acts_first(active, foe, name):
    def priority(move):
        info = move_info(move)
        return 1 if info and info['effect'] == 'PRIORITY_HIT' else (-1 if info and info['effect'] == 'VITAL_THROW' else 0)
    own = priority(name)
    enemy = max((priority(move) for move, pp in zip(getattr(foe, 'moves', ()),
                                                   getattr(foe, 'pp', ())) if pp > 0), default=1)
    if own != enemy:
        return own > enemy
    speed, other = stat(active, 2), stat(foe, 2)
    return speed is not None and other is not None and speed > other
