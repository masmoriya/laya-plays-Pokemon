import json

import pytest

from jpp.local_model import LocalModelClient


def test_local_model_requires_auth_for_remote_http():
    with pytest.raises(ValueError, match="HTTPS"):
        LocalModelClient(base_url="http://models.example/v1")


def test_local_model_health_checks_selected_model(monkeypatch):
    client = LocalModelClient(model="qwen-test")
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: {
        "data": [{"id": "qwen-test"}]
    })
    assert client.health() == {
        "status": "ok",
        "model": "qwen-test",
        "base_url": "http://127.0.0.1:8767/v1",
    }


def test_local_model_parses_structured_response(monkeypatch):
    client = LocalModelClient()
    seen = {}

    def request(path, payload=None, timeout=None):
        seen.update(path=path, payload=payload)
        return {
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"mode": "overworld"})
            }}],
            "usage": {"prompt_tokens": 12},
        }

    monkeypatch.setattr(client, "_request", request)
    value, usage = client.structured(
        [{"role": "user", "content": "read"}], {"type": "object"}, max_tokens=42
    )
    assert value == {"mode": "overworld"}
    assert usage == {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12}
    from jpp.agent.usage import UsageTotals
    totals = UsageTotals()
    totals.record("luna", **usage)
    assert totals.snapshot()["luna"]["input_tokens"] == 12
    assert seen["path"] == "chat/completions"
    assert seen["payload"]["model"] == client.model
    assert seen["payload"]["max_tokens"] == 42
    assert seen["payload"]["response_format"]["type"] == "json_schema"
