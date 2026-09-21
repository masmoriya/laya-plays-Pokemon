"""Jev's typed, closed-set judgments for adapter-neutral play."""

from types import SimpleNamespace

from ...policy import Policy, questions_for


class JevProvider:
    def __init__(self, policy=None):
        self.policy = policy or Policy()
        self.model = self.policy.client.model

    def decide_tactical(self, state, options):
        branch = SimpleNamespace(kind=state.get("decision_kind", "generic"),
                                 state=state, options=options)
        decision = self.policy.decide(branch)
        if decision.fell_back:
            raise RuntimeError(decision.reason)
        return {"action": decision.option, "probabilities": decision.probabilities,
                "confidence": decision.confidence, "nouls": decision.nouls,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "total_tokens": decision.total_tokens,
                "actual_cost_usd": decision.actual_cost_usd,
                "commentary": "",
                "model_input": {
                    "model": self.policy.client.model,
                    "state": state,
                    "questions": questions_for(branch),
                }}

    def decide_strategy(self, state, memory):
        return {"objective": state.get("objective", "Continue current route")}

    def recover(self, state, history):
        return {"action": "replan", "commentary": "Route stalled; replanning."}

    def generate_commentary(self, event):
        return event.get("commentary", "Jev is deciding.")
