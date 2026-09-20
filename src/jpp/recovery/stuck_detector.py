"""Bounded progress detector for unattended runs."""

from collections import Counter, deque


class StuckDetector:
    def __init__(self, window=24, warning=0.70, recovery=0.85):
        self.history = deque(maxlen=window)
        self.warning_threshold = warning
        self.recovery_threshold = recovery
        self.recovery_attempts = 0

    def observe(self, state, objective=""):
        point = (state.map_id, state.x, state.y, state.in_battle, objective)
        self.history.append(point)
        return self.score

    @property
    def score(self):
        if len(self.history) < 4:
            return 0.0
        locations = Counter(self.history)
        repeated = max(locations.values()) / len(self.history)
        recent = list(self.history)[-8:]
        no_progress = len({(item[0], item[1], item[2]) for item in recent}) <= 2
        score = repeated * 0.65 + (0.35 if no_progress else 0.0)
        if self.recovery_attempts:
            score += min(0.25, self.recovery_attempts * 0.08)
        return round(min(1.0, score), 2)

    @property
    def needs_warning(self):
        return self.score >= self.warning_threshold

    @property
    def needs_recovery(self):
        return self.score >= self.recovery_threshold

    def mark_recovery(self):
        self.recovery_attempts += 1

    def clear(self):
        self.history.clear()
        self.recovery_attempts = 0
