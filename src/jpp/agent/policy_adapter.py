"""Adapt intent providers to legacy closed-set loop policy."""

import time

from ..policy import Decision, default_option


class ProviderPolicy:
    def __init__(self, provider, fallback=None):
        self.provider = provider
        self.fallback = fallback

    def decide(self, branch, forced=False):
        fallback, reason = default_option(branch)
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
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                model=getattr(self.provider, "model", "provider"),
            )
        except Exception as exc:
            return Decision(
                option=fallback,
                fell_back=True,
                reason=f"{type(exc).__name__}: {exc}; {reason}",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )

