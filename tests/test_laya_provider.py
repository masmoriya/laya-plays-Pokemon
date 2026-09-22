import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError

import pytest

from jpp.agent.factory import provider_from_env
from jpp.agent.providers.laya_provider import LayaProvider
from jpp.laya_sidecar import _questions


@pytest.fixture(autouse=True)
def isolated_machine_config(monkeypatch, tmp_path):
    monkeypatch.setattr('jpp.laya_config.CONFIG', tmp_path / 'laya.local.json')


def test_local_external_checkpoint_setting_and_environment_override(monkeypatch, tmp_path):
    from jpp.laya_config import setting
    monkeypatch.delenv('LAYA_MODEL_PATH', raising=False)
    (tmp_path / 'laya.local.json').write_text(json.dumps({'model_path': '/Volumes/external/laya'}))
    assert setting('model_path') == '/Volumes/external/laya'
    monkeypatch.setenv('LAYA_MODEL_PATH', '/tmp/explicit-model')
    assert setting('model_path') == '/tmp/explicit-model'


def _sidecar(response, status=200):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps({"status": "ok", "model": "multilingual", "context_packing_version": 2}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            size = int(self.headers["Content-Length"])
            seen.append(json.loads(self.rfile.read(size)))
            payload = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}", seen, server


def test_laya_provider_translates_closed_set_response():
    url, seen, server = _sidecar({
        "action": "move_a", "probabilities": {"move_a": 0.8, "move_b": 0.2},
        "confidence": 0.8, "model": "laya-rl-agent", "input_tokens": 42,
    })
    try:
        provider = LayaProvider(url=url)
        answer = provider.decide_tactical({"decision_kind": "battle"}, {"move_a": "safe", "move_b": "risky"})
    finally:
        server.shutdown()
    assert seen == [{"state": {"decision_kind": "battle"}, "options": {"move_a": "safe", "move_b": "risky"}}]
    assert answer["action"] == "move_a"
    assert answer["actual_cost_usd"] == 0.0
    assert provider.model == "laya-rl-agent"
    assert answer["model_input"] == {
        "state": {"decision_kind": "battle"},
        "questions": _questions({"move_a": "safe", "move_b": "risky"}),
    }


def test_laya_provider_accepts_low_confidence_legal_choice_by_default():
    url, _, server = _sidecar({
        "action": "move_a", "probabilities": {"move_a": 0.517, "move_b": 0.483},
        "confidence": 0.0814,
    })
    try:
        answer = LayaProvider(url=url).decide_tactical(
            {}, {"move_a": "safe", "move_b": "risky"}
        )
    finally:
        server.shutdown()
    assert answer["action"] == "move_a"
    assert answer["confidence"] == 0.0814


def test_old_sidecar_cannot_silently_truncate_journey_context():
    url, _, server = _sidecar({'action': 'a', 'confidence': .8, 'probabilities': {'a': .8}})
    try:
        with pytest.raises(RuntimeError, match='Restart the Laya sidecar'):
            LayaProvider(url=url).decide_tactical({'journey': {}}, {'a': 'Confirm', 'b': 'Cancel'})
    finally:
        server.shutdown()


def test_laya_provider_advances_single_legal_action_without_sidecar_call():
    provider = LayaProvider(url="http://127.0.0.1:1", timeout=0.01)
    answer = provider.decide_tactical({}, {"a": "advance dialogue"})
    assert answer["action"] == "a"
    assert answer["request_made"] is False
    assert answer["total_tokens"] == 0
    assert "model_input" not in answer


@pytest.mark.parametrize("response", [
    {"action": "not_legal", "probabilities": {}, "confidence": 0.9},
    {"action": "move_a", "probabilities": {}, "confidence": 0.2},
    {"action": "move_a", "probabilities": {}, "confidence": "high"},
    {"action": "move_a", "probabilities": [] , "confidence": 0.9},
])
def test_laya_provider_rejects_unusable_decisions(response):
    url, _, server = _sidecar(response)
    try:
        with pytest.raises(ValueError):
            LayaProvider(url=url, min_confidence=0.55).decide_tactical(
                {}, {"move_a": "safe", "move_b": "other"}
            )
    finally:
        server.shutdown()


def test_laya_provider_rejects_unavailable_sidecar():
    with pytest.raises(RuntimeError, match="sidecar"):
        LayaProvider(url="http://127.0.0.1:1", timeout=0.01).decide_tactical(
            {}, {"move_a": "safe", "move_b": "other"}
        )


def test_laya_provider_retries_transient_sidecar_failure_and_preserves_error_detail():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(1)
            if len(calls) == 1:
                payload = b'{"error":"inference failed: temporary model worker error"}'
                self.send_response(500)
            else:
                payload = json.dumps({
                    "action": "move_a", "probabilities": {"move_a": 1.0},
                    "confidence": 0.01,
                }).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        answer = LayaProvider(url=f"http://127.0.0.1:{server.server_port}").decide_tactical(
            {}, {"move_a": "safe", "move_b": "other"}
        )
    finally:
        server.shutdown()
    assert answer["action"] == "move_a"
    assert len(calls) == 2


def test_laya_provider_surfaces_terminal_http_error_detail():
    url, _, server = _sidecar({"error": "inference failed: bad prompt"}, status=500)
    try:
        with pytest.raises(RuntimeError, match="bad prompt"):
            LayaProvider(url=url).decide_tactical(
                {}, {"move_a": "safe", "move_b": "other"}
            )
    finally:
        server.shutdown()


def test_factory_selects_laya():
    provider = provider_from_env("laya")
    assert isinstance(provider, LayaProvider)
    assert provider.usage_provider == "laya"


def test_laya_provider_reads_sidecar_health():
    url, _, server = _sidecar({})
    try:
        assert LayaProvider(url=url).health() == {"status": "ok", "model": "multilingual", "context_packing_version": 2}
    finally:
        server.shutdown()


def test_laya_provider_uses_sidecar_host_and_port_env(monkeypatch):
    monkeypatch.delenv("LAYA_BASE_URL", raising=False)
    monkeypatch.setenv("LAYA_HOST", "127.0.0.1")
    monkeypatch.setenv("LAYA_PORT", "9876")
    assert LayaProvider().url == "http://127.0.0.1:9876"


def test_laya_health_explains_missing_checkpoint(monkeypatch):
    monkeypatch.delenv("LAYA_MODEL_PATH", raising=False)
    provider = LayaProvider(url="http://127.0.0.1:1", timeout=0.01)
    with pytest.raises(RuntimeError, match="LAYA_MODEL_PATH"):
        provider.health()


def test_laya_health_can_start_a_configured_local_sidecar(monkeypatch):
    class Process:
        def __init__(self):
            self.command = None
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    process = Process()
    monkeypatch.setenv("LAYA_MODEL_PATH", "/tmp/laya-model")
    monkeypatch.setenv("LAYA_STARTUP_TIMEOUT_S", "0.1")
    provider = LayaProvider(url="http://127.0.0.1:9876", timeout=0.01)
    responses = iter([URLError(ConnectionRefusedError("connection refused")),
                      {"status": "ok", "model": "multilingual", "context_packing_version": 2},
                      {"status": "ok", "model": "multilingual", "context_packing_version": 2}])

    def health_request():
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(provider, "_health_request", health_request)

    def start(command, **kwargs):
        process.command = command
        return process

    monkeypatch.setattr("jpp.agent.providers.laya_provider.subprocess.Popen", start)
    assert provider.health() == {"status": "ok", "model": "multilingual", "context_packing_version": 2}
    assert process.command[-2:] == ["--model-path", "/tmp/laya-model"]
    provider.close()
    assert process.terminated


def test_laya_sidecar_builds_one_closed_set_choice_question():
    assert _questions({"move_a": "safe move"}) == {
        "next_action": {
            "type": "choice",
            "instructions": "Choose exactly one legal next action for the current Pokemon game state.",
            "criteria": {"move_a": "safe move"},
        }
    }


def test_busy_sidecar_is_not_immediately_retried():
    url, seen, server = _sidecar({'error': 'previous decision still running'}, status=503)
    try:
        with pytest.raises(RuntimeError, match='previous decision still running'):
            LayaProvider(url=url).decide_tactical({}, {'a': 'Confirm', 'b': 'Cancel'})
    finally:
        server.shutdown()
    assert len(seen) == 1


def test_old_sidecar_cannot_claim_navigation_memory_support():
    with pytest.raises(RuntimeError, match='Restart'):
        LayaProvider._check_capabilities({'status': 'ok', 'context_packing_version': 1})
