"""Compatibility provider backed by existing closed-set policy."""

from ...policy import Policy


class JevProvider:
    def __init__(self, policy=None):
        self.policy = policy or Policy(enabled=False)

    def decide_tactical(self, state, options):
        # Existing loop still owns Branch -> button translation. This adapter exposes
        # same intent shape for new orchestration code.
        return {"action": next(iter(options), "wait"), "commentary": "Choosing legal action."}

    def decide_strategy(self, state, memory):
        return {"objective": state.get("objective", "Continue current route")}

    def recover(self, state, history):
        return {"action": "replan", "commentary": "Route stalled; replanning."}

    def generate_commentary(self, event):
        return event.get("commentary", "Jev is deciding.")

