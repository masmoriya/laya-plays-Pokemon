"""Adapt intent providers to legacy closed-set loop policy."""

import time

from ..policy import Decision, default_option


class ProviderPolicy:
    def __init__(self, provider, fallback=None):
        self.provider = provider
        self.fallback = fallback

    def decide(self, branch, forced=False):
        fallback, _ = default_option(branch)
        if forced:
            return Decision(option=fallback, fell_back=True, reason="stuck safety cap")
        started = time.monotonic()
        try:
            answer = self.provider.decide_tactical(branch.state, branch.options)
            option = answer.get("action")
            if option not in branch.options:
                raise ValueError("provider action outside allowlist")
            return Decision(
                option=option,
                reason=answer.get("commentary", ""),
                probabilities=answer.get("probabilities", {}),
                confidence=answer.get("confidence"),
                nouls=answer.get("nouls", {}),
                input_tokens=answer.get("input_tokens", 0),
                output_tokens=answer.get("output_tokens", 0),
                total_tokens=answer.get("total_tokens", 0),
                actual_cost_usd=answer.get("actual_cost_usd", answer.get("cost_usd")),
                latency_ms=answer.get("latency_ms") or round((time.monotonic() - started) * 1000, 1),
                request_made=answer.get("request_made", True),
                model=getattr(self.provider, "model", "provider"),
                model_input=answer.get("model_input"),
            )
        except Exception as exc:
            return Decision(
                option=fallback,
                fell_back=True,
                reason=f"{type(exc).__name__}: {exc}",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
