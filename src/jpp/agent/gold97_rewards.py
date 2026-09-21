"""Verified achievements survive roster changes and checkpoint rewinds."""
from collections import Counter
import json

from .old_species import hack_exclusive

DEFAULT_WEIGHTS = {'xp_tenth': 1, 'level': 10, 'capture': 25,
                   'evolution': 25, 'milestone': 100, 'discovery': 50}
# Pinned data/growth_rates.asm; the cartridge uses integer arithmetic.
GROWTH = ((1, 1, 0, 0, 0), (3, 4, 10, 0, 30), (3, 4, 20, 0, 70),
          (6, 5, -15, 100, 140), (4, 5, 0, 0, 0), (5, 4, 0, 0, 0))


def level_exp(level, growth):
    if growth not in range(len(GROWTH)):
        return None
    a, b, c, d, e = GROWTH[growth]
    return max(0, a * level ** 3 // b + c * level ** 2 + d * level - e)


def progress_units(mon):
    xp, rate = getattr(mon, 'experience', None), getattr(mon, 'growth_rate', None)
    level = getattr(mon, 'level', 0)
    if xp is None or rate is None or not 1 <= level <= 100:
        return None
    start = level_exp(level, rate)
    end = level_exp(level + 1, rate)
    if start is None or xp < start or (level < 100 and xp >= end):
        return None  # XP and level are written in different frames.
    return level * 10 + (min(9, (xp - start) * 10 // (end - start)) if level < 100 else 0)


class RewardLedger:
    def __init__(self, memory, weights=None):
        self.memory = memory
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.db = memory.db
        self.db.execute('CREATE TABLE IF NOT EXISTS agent_rewards(run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        row = self.db.execute('SELECT payload FROM agent_rewards WHERE run_id=?', (memory.run_id,)).fetchone()
        self.data = json.loads(row[0]) if row else {'version': 1, 'records': {}, 'claims': [],
                                                  'total': 0, 'recent': [], 'baseline': False}
        self.reset_observation()

    def reset_observation(self):
        self.previous = {}
        self.battle_before = None
        self.battle_caught = set()
        self.battle_xp = {}
        self.capture_target = None
        self.balls_before = None
        self.participants = set()
        self.was_battle = False
        self.settle = 0
        self.last_gains = {}
        self.world_id = id(self.memory.world)

    def save(self):
        self.db.execute('INSERT OR REPLACE INTO agent_rewards VALUES(?,?)',
                        (self.memory.run_id, json.dumps(self.data)))
        self.db.commit()

    def claim(self, key, kind, amount=1, label=''):
        if key in self.data['claims']:
            return
        self.data['claims'].append(key)
        points = self.weights[kind] * amount
        self.data['total'] += points
        self.data['recent'] = (self.data['recent'] + [{'kind': kind, 'points': points,
                                                     'label': label}])[-12:]

    def observe_exploration(self, state, *, overworld):
        """Reward actual new maps once, retaining discoveries across rewinds."""
        if (not overworld or state.in_battle
                or not getattr(state, 'mechanics_verified', False)):
            return
        group, number = state.map_group, state.map_number
        if (not group or not number or state.x is None or state.y is None
                or not 0 <= state.x < state.map_width
                or not 0 <= state.y < state.map_height):
            return
        key = f'{group:02X}:{number:02X}'
        if 'discovered_maps' not in self.data:
            # Existing saves and the starting location are the baseline.
            known = {k for k, area in self.memory.world['maps'].items()
                     if area.get('visited')}
            for connection in self.memory.world.get('journey_strategy', {}).get('connections', ()):
                known.update((connection['from'], connection['to']))
            self.data['discovered_maps'] = sorted(known | {key})
            self.save()
        elif key not in self.data['discovered_maps']:
            self.data['discovered_maps'].append(key)
            self.claim(f'discovery:{key}', 'discovery', label=state.area_name)
            self.save()

    def observe(self, state, route):
        if id(self.memory.world) != self.world_id:
            self.reset_observation()
        if not getattr(state, 'mechanics_verified', False):
            return
        roster = tuple(state.party) + tuple(getattr(state, 'box_roster', ()))
        counts = Counter(m.identity for m in roster if getattr(m, 'identity', None))
        unique = {m.identity: m for m in roster if getattr(m, 'identity', None)
                  and counts[m.identity] == 1 and progress_units(m) is not None}
        before = json.dumps(self.data, sort_keys=True)
        caught = set(getattr(state, 'pokedex_caught_ids', ()))
        completed = set(route.completed) - set(route.manual_history)
        if not self.data['baseline']:
            if not state.party:
                return
            self.data['claims'] += [f'capture:{s}' for s in caught]
            self.data['claims'] += [f'evolution:{s}' for s in caught]
            self.data['claims'] += [f'milestone:{s}' for s in completed]
            self.data['baseline'] = True
        if state.in_battle and not self.was_battle:
            self.battle_before = {k: m.experience for k, m in unique.items()}
            self.battle_caught = caught
            self.battle_xp = {}
            self.capture_target = None
            self.balls_before = getattr(state, 'poke_ball_count', None)
            self.participants.clear()
            self.last_gains = {}
        if state.in_battle and getattr(state.battle, 'kind', None) == 'wild':
            self.capture_target = getattr(state.battle.opponent, 'species_id', self.capture_target)
        slot = getattr(state, 'active_slot', None)
        mask = getattr(state, 'battle_participants', None)
        if state.in_battle and mask is not None:
            self.participants.update(m.identity for i, m in enumerate(state.party) if mask & (1 << i))
        if state.in_battle and slot is not None and 0 <= slot < len(state.party):
            self.participants.add(state.party[slot].identity)
        if state.in_battle:
            for mon in roster:
                if mon.identity and mon.experience is not None:
                    self.battle_xp[mon.identity] = max(self.battle_xp.get(mon.identity, 0), mon.experience)
        if self.was_battle and not state.in_battle:
            self.settle = 180  # Allow battle XP/level/evolution writes to settle.
        eligible = self.battle_before is not None and (state.in_battle or self.settle > 0)
        balls = getattr(state, 'poke_ball_count', None)
        if eligible and balls is not None and self.balls_before is not None and balls < self.balls_before:
            for species in (caught - self.battle_caught) & {self.capture_target}:
                names = getattr(state, 'pokedex_species', ())
                if 0 < species < len(names) and hack_exclusive(names[species]):
                    self.claim(f'capture:{species}', 'capture', label=names[species])
        records = self.data['records']
        for key, mon in unique.items():
            units = progress_units(mon)
            old = records.get(key)
            if old is None:
                records[key] = {'units': units, 'level': mon.level, 'species': mon.species_id}
                continue
            prior = self.previous.get(key)
            participant = key in self.participants or str(mon.held_item).upper() == 'EXP SHARE'
            gain = (mon.experience - self.battle_before.get(key, mon.experience)) if eligible else 0
            if gain > 0 and participant and mon.experience <= self.battle_xp.get(key, 0):
                self.last_gains[key] = gain
                for unit in range(old['units'] + 1, units + 1):
                    self.claim(f'xp:{key}:{unit}', 'xp_tenth', label=mon.species)
                for level in range(old['level'] + 1, mon.level + 1):
                    self.claim(f'level:{key}:{level}', 'level', label=mon.species)
            # Transfers alone cannot prove an evolution. Require a continuous
            # observed individual, a changed species, and unchanged/growing XP.
            if (prior and prior.species_id != mon.species_id and
                    mon.experience >= prior.experience):
                self.claim(f'evolution:{mon.species_id}', 'evolution', label=mon.species)
            old.update(units=max(old['units'], units), level=max(old['level'], mon.level),
                       species=mon.species_id)
        for step in completed:
            self.claim(f'milestone:{step}', 'milestone', label=str(step))
        self.previous = unique
        self.was_battle = state.in_battle
        if not state.in_battle and self.settle:
            self.settle -= 1
        if not state.in_battle and not self.settle:
            self.battle_before = None
        if before != json.dumps(self.data, sort_keys=True):
            self.save()

    def summary(self):
        return {'points': self.data['total'], 'recent': self.data['recent'],
                'xp_gains': dict(self.last_gains)}
