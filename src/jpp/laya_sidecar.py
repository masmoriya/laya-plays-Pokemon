"""Local-only HTTP service that keeps a Laya decision model loaded."""

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .laya_config import setting

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MODEL = "multilingual"


def _questions(options):
    return {
        "next_action": {
            "type": "choice",
            "instructions": "Choose exactly one legal next action for the current Pokemon game state.",
            "criteria": {key: str(description or key) for key, description in options.items()},
        }
    }


class LayaService:
    def __init__(self, model_path, model=DEFAULT_MODEL, device=None):
        if not model_path:
            raise ValueError("LAYA_MODEL_PATH is required; download weights before starting the sidecar")
        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"local Laya model directory not found: {model_path}")
        try:
            import laya
        except ImportError as exc:
            raise RuntimeError("install the Laya extra with: uv sync --extra laya") from exc
        self.model_name = model
        self.agent = laya.load(model_path, device=device)
        # The local model is shared by ThreadingHTTPServer. Laya's sequence
        # builder/model cache is not guaranteed to be re-entrant, so serialize
        # inference and let the client retry a transient 5xx safely.
        self._predict_lock = threading.Lock()

    def decide(self, state, options):
        if not isinstance(state, dict) or not isinstance(options, dict) or not options:
            raise ValueError("state and non-empty options objects are required")
        if len(options) == 1:
            action = next(iter(options))
            return {
                "action": action,
                "probabilities": {action: 1.0},
                "confidence": 1.0,
                "model": self.model_name,
                "input_tokens": 0,
                "actual_cost_usd": 0.0,
                "latency_ms": 0.0,
            }
        started = time.monotonic()
        with self._predict_lock:
            from .agent.tactical_context import pack_context
            questions = _questions(options)
            packed, context = pack_context(state, questions, self.agent)
            result = self.agent.predict(packed, questions)
        answer = result["answers"]["next_action"]
        return {
            "action": answer["choice"],
            "probabilities": answer["probabilities"],
            "confidence": answer["confidence"],
            "model": result.get("model", self.model_name),
            "input_tokens": (result.get("usage") or {}).get("input_tokens", 0),
            "actual_cost_usd": 0.0,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "model_input": {"state": packed, "questions": questions, "context": context},
        }


def serve(service, host=DEFAULT_HOST, port=DEFAULT_PORT):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self._send(200, {"service": "laya-sidecar", "health": "/health", "decision_endpoint": "/v1/decide"})
            elif self.path == "/health":
                self._send(200, {"status": "ok", "model": service.model_name,
                                 "context_packing_version": 1})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/decide":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 262144:
                    self._send(413, {"error": "Decision payload exceeds 256 KiB"})
                    return
                payload = json.loads(self.rfile.read(length))
                self._send(200, service.decide(payload.get("state"), payload.get("options")))
            except (ValueError, json.JSONDecodeError, KeyError) as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": f"inference failed: {exc}"})

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Laya sidecar ready at http://{host}:{port}", flush=True)
    server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a local Laya sidecar")
    parser.add_argument("--host", default=os.environ.get("LAYA_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAYA_PORT", DEFAULT_PORT)))
    parser.add_argument("--model-path", default=setting("model_path"))
    parser.add_argument("--model", default=os.environ.get("LAYA_MODEL", DEFAULT_MODEL))
    parser.add_argument("--device", default=setting("device"))
    args = parser.parse_args(argv)
    serve(LayaService(args.model_path, args.model, args.device), args.host, args.port)


if __name__ == "__main__":
    main()
