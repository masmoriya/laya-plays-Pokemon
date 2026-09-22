"""Run-local navigation measurements from observed cartridge outcomes."""
from collections import Counter

from .agent.navigation_policy import COLLECTIBLES
from .agent.object_memory import RESOLVED_OUTCOMES
from .agent.progress_contract import progress_stamp


class NavigationMetrics:
    def __init__(self, memory):
        objects = memory.world.get('journey_strategy', {}).get('npcs', {})
        self.baseline = {key: obj.get('outcome') for key, obj in objects.items()}
        self.observed = set()
        self.edges = Counter()
        self.positions = set()
        self.last = None
        self.previous = None
        self.reversals = 0
        self.transitions = 0
        self.departures = []
        self.progress = None
        self.progress_frame = 0
        self.longest_no_progress = 0

    def observe(self, owner, state, overworld, frames):
        objects = owner.strategy.data['npcs']
        self.observed.update(key for key, obj in objects.items()
                             if obj.get('visible') and obj.get('category') in COLLECTIBLES)
        stamp = (owner.memory.world.get('discovery_revision', 0), progress_stamp(owner.memory))
        self.longest_no_progress = max(self.longest_no_progress, frames - self.progress_frame)
        if stamp != self.progress:
            self.progress, self.progress_frame = stamp, frames
        if not overworld or state.in_battle or state.x is None or state.y is None:
            return
        key = f'{state.map_group:02X}:{state.map_number:02X}'
        point = (key, state.x, state.y)
        if point == self.last:
            return
        self.positions.add(point)
        if self.last and self.last[0] != key:
            self.transitions += 1
            pending = [obj['id'] for obj in objects.values()
                       if obj.get('map') == self.last[0] and obj.get('category') in COLLECTIBLES
                       and obj.get('outcome') not in RESOLVED_OUTCOMES
                       and obj.get('reachability') == 'reachable']
            if pending:
                self.departures.append({'map': self.last[0], 'pending': pending})
        elif self.last and abs(point[1] - self.last[1]) + abs(point[2] - self.last[2]) == 1:
            self.edges[(self.last, point)] += 1
            if point == self.previous:
                self.reversals += 1
        self.previous, self.last = self.last, point

    def summary(self, owner):
        objects = owner.strategy.data['npcs']
        pickups = [obj['id'] for key, obj in objects.items()
                   if obj.get('outcome') in {'collected', 'harvested'}
                   and self.baseline.get(key) not in {'collected', 'harvested'}]
        pending = [key for key in sorted(self.observed)
                   if objects.get(key, {}).get('outcome') not in RESOLVED_OUTCOMES]
        steps = sum(self.edges.values())
        return {'steps': steps, 'unique_positions': len(self.positions),
                'repeated_steps': steps - len(self.edges),
                'immediate_reversals': self.reversals, 'map_transitions': self.transitions,
                'new_pickups': pickups,
                'new_harvests': [key for key in pickups if objects[key].get('outcome') == 'harvested'],
                'observed_collectibles': len(self.observed),
                'pending_collectibles': pending,
                'departures_with_pending_collectibles': self.departures,
                'longest_no_progress_frames': self.longest_no_progress,
                'coverage_scope': 'Only observed collectibles; hidden or unseen items are not counted.'}
