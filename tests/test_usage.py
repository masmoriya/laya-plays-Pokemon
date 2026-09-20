from jpp.agent.usage import UsageTotals
from jpp.live_ui import format_tokens


def test_dashboard_token_labels_keep_exact_counts():
    assert format_tokens(1_234_567) == "1,234,567"


def test_jev_usage_keeps_token_sides_rate_and_estimate():
    usage = UsageTotals()
    usage.record("jev", input_tokens=1_000, output_tokens=250, latency_ms=500)

    jev = usage.snapshot()["jev"]
    assert (jev["input_tokens"], jev["output_tokens"], jev["total_tokens"]) == (1000, 250, 1250)
    assert jev["tokens_per_second"] == 2500.0
    assert jev["input_tokens_per_second"] == 2000.0
    assert jev["output_tokens_per_second"] == 500.0
    assert jev["estimated_cost_usd"] == 0.000042
    assert jev["actual_cost_usd"] is None


def test_luna_cost_stays_unavailable_without_a_configured_rate():
    usage = UsageTotals()
    usage.record("luna", input_tokens=100, output_tokens=50, latency_ms=100)

    luna = usage.snapshot()["luna"]
    assert luna["total_tokens"] == 150
    assert luna["estimated_cost_usd"] is None
    assert luna["actual_cost_usd"] is None


def test_provider_reported_actual_cost_is_preserved():
    usage = UsageTotals()
    usage.record("jev", input_tokens=10, actual_cost_usd=0.12)

    assert usage.snapshot()["jev"]["actual_cost_usd"] == 0.12
