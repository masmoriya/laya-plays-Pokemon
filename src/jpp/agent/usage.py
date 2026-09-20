"""Small, provider-neutral model usage totals for the live dashboard."""

from dataclasses import dataclass
import os


def _rate_from_env(name):
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw) / 1_000_000
    except ValueError:
        return None


@dataclass
class UsageBucket:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    has_estimate: bool = False
    actual_cost_usd: float = 0.0
    has_actual: bool = False

    def record(self, *, input_tokens=0, output_tokens=0, total_tokens=None,
               latency_ms=0, estimated_cost_usd=None, actual_cost_usd=None):
        input_tokens = max(0, int(input_tokens or 0))
        output_tokens = max(0, int(output_tokens or 0))
        total_tokens = max(input_tokens + output_tokens,
                           int(total_tokens or 0))
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        self.latency_ms += max(0.0, float(latency_ms or 0))
        if estimated_cost_usd is not None:
            self.estimated_cost_usd += max(0.0, float(estimated_cost_usd))
            self.has_estimate = True
        if actual_cost_usd is not None:
            self.actual_cost_usd += max(0.0, float(actual_cost_usd))
            self.has_actual = True

    def snapshot(self):
        seconds = self.latency_ms / 1000
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "input_tokens_per_second": round(self.input_tokens / seconds, 1) if seconds else None,
            "output_tokens_per_second": round(self.output_tokens / seconds, 1) if seconds else None,
            "tokens_per_second": round(self.total_tokens / seconds, 1) if seconds else None,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6) if self.has_estimate else None,
            "actual_cost_usd": round(self.actual_cost_usd, 6) if self.has_actual else None,
        }


class UsageTotals:
    """Accumulate completed model requests without claiming unavailable billing data."""

    def __init__(self):
        self._buckets = {"jev": UsageBucket(), "laya": UsageBucket(), "luna": UsageBucket()}
        self._rates = {
            "jev": (_rate_from_env("JEV_INPUT_PRICE_PER_1M") or 0.042 / 1_000_000,
                    _rate_from_env("JEV_OUTPUT_PRICE_PER_1M")),
            "laya": (0.0, 0.0),
            "luna": (_rate_from_env("CODEX_INPUT_PRICE_PER_1M"),
                      _rate_from_env("CODEX_OUTPUT_PRICE_PER_1M")),
        }

    def record(self, provider, *, input_tokens=0, output_tokens=0, total_tokens=None,
               latency_ms=0, estimated_cost_usd=None, actual_cost_usd=None):
        if provider not in self._buckets:
            return
        input_tokens = max(0, int(input_tokens or 0))
        output_tokens = max(0, int(output_tokens or 0))
        if estimated_cost_usd is None and (input_tokens or output_tokens):
            input_rate, output_rate = self._rates[provider]
            if input_rate is not None or output_rate is not None:
                estimated_cost_usd = input_tokens * (input_rate or 0)
                estimated_cost_usd += output_tokens * (output_rate or 0)
        self._buckets[provider].record(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
            actual_cost_usd=actual_cost_usd,
        )

    def snapshot(self):
        return {name: bucket.snapshot() for name, bucket in self._buckets.items()}
