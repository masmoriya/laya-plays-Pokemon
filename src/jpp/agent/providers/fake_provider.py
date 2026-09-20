"""Deterministic provider for offline runs and tests."""


class FakeProvider:
    def decide_tactical(self, state, options):
        return {"action": next(iter(options), "wait"), "commentary": "Following safe route."}

    def decide_strategy(self, state, memory):
        return {"objective": state.get("objective", "Continue journey")}

    def recover(self, state, history):
        return {"action": "replan", "commentary": "Trying another route."}

    def generate_commentary(self, event):
        return event.get("commentary", "Jev is watching the run.")

