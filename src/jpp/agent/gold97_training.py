"""Small training budgets keyed to fresh journey evidence, never wall-clock speed."""
from statistics import median
from dataclasses import asdict, is_dataclass
from ..decode import Mon
from .gold97_damage import incoming, attacks
from .gold97_rewards import progress_units, DEFAULT_WEIGHTS
from .gold97_encounters import healthy
from .gold97_navigation import STEPS


class Training:
    def __init__(self, memory):
        self.memory = memory
        self.levels = memory.world.get('training', {}).get('levels', [])
        self.last_saved = 0
        self.was_battle = False
        self.last_kind = None
        self.last_foe = None
        self.last_frame = None
        self.intent = ''

    @property
    def data(self):
        return self.memory.world.setdefault('training', {'evidence': None, 'frames': 0,
                                                        'battles': 0, 'active': False,
                                                        'exhausted': False})

    def observe(self, state, route):
        data = self.data
        strategy = self.memory.world.get('journey_strategy', {})
        evidence = [route.now, len(strategy.get('clues', []))]
        if evidence != data['evidence']:
            data.update(evidence=evidence, frames=0, battles=0, exhausted=False, active=False)
            data.pop('readiness_failure', None)
        foe = getattr(state.battle, 'opponent', None)
        if state.in_battle and not self.was_battle and getattr(foe, 'level', None):
            self.levels = (self.levels + [foe.level])[-5:]
            data['levels'] = self.levels
            if state.battle.kind == 'trainer' and is_dataclass(foe):
                data.setdefault('opponents', {})[state.area_name] = asdict(foe)
        if state.in_battle:
            self.last_kind = state.battle.kind
            if is_dataclass(foe):
                self.last_foe = asdict(foe)
        if (self.was_battle and not state.in_battle and self.last_kind == 'trainer'
                and getattr(state, 'battle_result', None) == 1):
            data.update(frames=0, battles=0, active=False, exhausted=False,
                        readiness_failure=self.last_foe)
        if self.was_battle and not state.in_battle and data['active']:
            data['battles'] += 1
        frame = getattr(state, 'frame_number', 0)
        if data['active'] and self.last_frame is not None and frame >= self.last_frame:
            data['frames'] += frame - self.last_frame
        transition = self.was_battle != state.in_battle
        self.last_frame, self.was_battle = frame, state.in_battle
        if data['battles'] >= 5 or data['frames'] >= 60 * 60 * 5:
            data.update(active=False, exhausted=True)
            self.intent = 'Continue journey'
        if frame - self.last_saved >= 600 or transition:
            self.memory.save()
            self.last_saved = frame

    def trainee(self, state):
        if len(state.party) < 2 or not self.levels:
            return None
        target = int(median(self.levels)) + 1
        candidates = [(m.level, i) for i, m in enumerate(state.party)
                      if healthy(m) and m.level < target and str(m.held_item).upper() != 'EXP SHARE']
        return min(candidates)[1] if candidates else None

    def required(self, state):
        """Training may preempt the Journey only after a verified trainer loss."""
        return bool(self.data.get('readiness_failure') and not self.data['exhausted']
                    and self.trainee(state) is not None)

    def lead(self, state):
        known = self.data.get('opponents', {}).get(state.area_name)
        if known:
            foe = Mon(**known)
            def matchup(index):
                mon = state.party[index]
                risk = incoming(foe, mon)
                hits = [e for _, e in attacks(mon, foe) if e.known]
                return (bool(risk and mon.hp > risk.high * 2),
                        max((e.expected for e in hits), default=0), mon.hp)
            return max((i for i, m in enumerate(state.party) if healthy(m)),
                       key=matchup, default=None)
        if 'gym' in state.area_name.casefold():
            return max((i for i, m in enumerate(state.party) if healthy(m)),
                       key=lambda i: state.party[i].level, default=None)
        return self.trainee(state)

    def direction(self, state, terrain):
        data = self.data
        trainee = self.trainee(state)
        if (data['exhausted'] or trainee is None or terrain is None or
                any(not healthy(m) for m in state.party)):
            if data['active']:
                data.update(active=False, exhausted=True)
            self.intent = 'Continue journey'
            return None
        origin = state.x, state.y
        grass = {0x10, 0x14, 0x18, 0x1C}
        # Deliberate detours use local grass already reached, never a guessed nest.
        if terrain.tile(origin) not in grass:
            return None
        options = [(d, (state.x + dx, state.y + dy)) for d, (dx, dy) in STEPS.items()]
        choices = [(d, cell) for d, cell in options if terrain.allows(cell, d)
                   and terrain.tile(cell) in grass]
        if not choices:
            return None
        data['active'] = True
        self.intent = f'Training {state.party[trainee].species.title()}'
        return choices[(data['frames'] // 36) % len(choices)][0]

    def summary(self, state, weights=None):
        weights = weights or DEFAULT_WEIGHTS
        target = int(median(self.levels)) + 1 if self.levels else None
        return {'intent': self.intent, 'encounters': self.data['battles'],
                'emulated_frames': self.data['frames'], 'exhausted': self.data['exhausted'],
                'deficits': [{'species': m.species, 'levels': max(0, target - m.level),
                              'progress_tenth': progress_units(m),
                              'points_to_next_level': ((10 - progress_units(m) % 10) * weights['xp_tenth'] + weights['level'])
                              if progress_units(m) is not None else None}
                             for m in state.party if target is not None and m.level < target]}
