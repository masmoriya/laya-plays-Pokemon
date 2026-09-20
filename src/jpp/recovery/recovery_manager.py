"""Safe recovery coordinator. Provider output is allowlisted before execution."""

from dataclasses import dataclass


ALLOWED_ACTIONS = frozenset({"replan", "reload_checkpoint", "wait"})


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    commentary: str


class RecoveryManager:
    def __init__(self, provider=None, checkpoint_loader=None):
        self.provider = provider
        self.checkpoint_loader = checkpoint_loader
        self.history: list[dict] = []

    def decide(self, state, history):
        try:
            answer = self.provider.recover(state, history) if self.provider else {"action": "replan"}
            action = answer.get("action", "wait")
            if action not in ALLOWED_ACTIONS:
                raise ValueError("recovery action outside allowlist")
        except Exception as exc:
            action = "wait"
            answer = {"commentary": f"Recovery paused: {type(exc).__name__}."}
        decision = RecoveryDecision(action, answer.get("commentary", "Jev is recovering."))
        self.history.append({"action": decision.action, "commentary": decision.commentary})
        if decision.action == "reload_checkpoint" and self.checkpoint_loader:
            self.checkpoint_loader()
        return decision

