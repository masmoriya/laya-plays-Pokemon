"""Strategic planner boundary. Deterministic until Luna is configured."""

from .objectives import OBJECTIVES


class Planner:
    def __init__(self, provider=None):
        self.provider = provider
        self.current = OBJECTIVES[1]
        self.completed: list[str] = []

    def choose(self, state, memories=()):
        if self.provider:
            answer = self.provider.decide_strategy(state, list(memories))
            requested = answer.get("objective")
            match = next((item for item in OBJECTIVES if item.key == requested), None)
            if match:
                self.current = match
        return self.current

    def complete(self, key):
        if key not in self.completed:
            self.completed.append(key)
        next_item = next((item for item in OBJECTIVES if item.key not in self.completed and item.parent == self.current.key), None)
        if next_item:
            self.current = next_item

