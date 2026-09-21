"""Local Laya sidecar client for closed-set tactical decisions."""

import errno
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ...laya_config import setting
from ...laya_sidecar import _questions

DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT_S = 3.0
DEFAULT_STARTUP_TIMEOUT_S = 30.0
_MAX_ATTEMPTS = 2
_RETRY_DELAY_S = 0.05
# Laya's confidence is useful telemetry, but the model's calibrated values are
# often below 0.55 even when it returns a legal action. Keep the gate opt-in so
# a valid closed-set answer is not silently replaced by the deterministic path.
DEFAULT_MIN_CONFIDENCE = 0.0


class LayaProvider:
    """Call a local Laya service; mechanics and fallback stay in the game loop."""

    usage_provider = "laya"

    def __init__(self, url=None, timeout=None, min_confidence=None):
        configured_url = url or os.environ.get("LAYA_BASE_URL")
        if configured_url:
            self.url = configured_url.rstrip("/")
        else:
            host = os.environ.get("LAYA_HOST", DEFAULT_HOST)
            port = os.environ.get("LAYA_PORT", str(DEFAULT_PORT))
            self.url = f"http://{host}:{port}".rstrip("/")
        self.timeout = float(timeout or os.environ.get("LAYA_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
        self.startup_timeout = float(
            os.environ.get("LAYA_STARTUP_TIMEOUT_S", DEFAULT_STARTUP_TIMEOUT_S)
        )
        self.min_confidence = float(
            min_confidence
            if min_confidence is not None
            else os.environ.get("LAYA_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
        )
        if not math.isfinite(self.min_confidence) or not 0 <= self.min_confidence <= 1:
            raise ValueError("LAYA_MIN_CONFIDENCE must be between 0 and 1")
        self.model = "laya-local"
        self._sidecar_process = None
        self._autostart_attempted = False

    def decide_tactical(self, state, options):
        if not options:
            raise ValueError("no legal actions to send to Laya")
        # Laya's choice head requires at least two candidates. A single legal
        # action is already fully determined by the controller, so advancing it
        # locally avoids the model's `selected index k out of range` failure.
        if len(options) == 1:
            action = next(iter(options))
            return {
                "action": action,
                "probabilities": {action: 1.0},
                "confidence": 1.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "actual_cost_usd": 0.0,
                "latency_ms": 0.0,
                "commentary": "Only legal action",
                "request_made": False,
            }
        model_input = {"state": state, "questions": _questions(options)}
        response = self._post({"state": state, "options": options})
        action = response.get("action")
        if action not in options:
            raise ValueError("Laya action outside allowlist")
        confidence = response.get("confidence")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Laya response has no numeric confidence")
        if confidence < self.min_confidence:
            raise ValueError(f"Laya confidence {confidence:.3f} below {self.min_confidence:.3f}")
        probabilities = response.get("probabilities", {})
        if not isinstance(probabilities, dict):
            raise ValueError("Laya probabilities must be an object")
        if any(key not in options for key in probabilities):
            raise ValueError("Laya probabilities contain an unknown action")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0
               for value in probabilities.values()):
            raise ValueError("Laya probabilities must contain finite non-negative numbers")
        self.model = str(response.get("model") or "laya-local")
        return {
            "action": action,
            "probabilities": probabilities,
            "confidence": float(confidence),
            "input_tokens": int(response.get("input_tokens") or 0),
            "output_tokens": 0,
            "total_tokens": int(response.get("input_tokens") or 0),
            "actual_cost_usd": 0.0,
            "latency_ms": float(response.get("latency_ms") or 0.0),
            "commentary": "",
            "model_input": model_input,
        }

    def decide_strategy(self, state, memory):
        return {"objective": state.get("objective", "Continue current route")}

    def recover(self, state, history):
        return {"action": "replan", "commentary": "Route stalled; replanning."}

    def generate_commentary(self, event):
        return event.get("commentary", "Laya is deciding.")

    def health(self):
        try:
            return self._health_request()
        except urllib.error.URLError as exc:
            if (self._is_connection_refused(exc) and self._start_local_sidecar()
                    and self._wait_for_sidecar()):
                return self._health_request()
            raise RuntimeError(self._unavailable_message(exc)) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(self._unavailable_message(exc)) from exc

    def close(self):
        """Stop only a sidecar that this provider started for the current run."""
        process = self._sidecar_process
        self._sidecar_process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _health_request(self):
        request = urllib.request.Request(
            self.url + "/health", headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as result:
            return json.loads(result.read())

    def _start_local_sidecar(self):
        if self._autostart_attempted:
            return False
        self._autostart_attempted = True
        enabled = os.environ.get("LAYA_AUTOSTART", "1").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return False
        model_path = setting("model_path")
        parsed = urlsplit(self.url)
        if not model_path or parsed.scheme != "http":
            return False
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            return False
        host = parsed.hostname or DEFAULT_HOST
        port = parsed.port or DEFAULT_PORT
        command = [
            sys.executable,
            "-m",
            "jpp.laya_sidecar",
            "--host",
            host,
            "--port",
            str(port),
            "--model-path",
            model_path,
        ]
        device = setting("device")
        if device:
            command.extend(["--device", device])
        try:
            self._sidecar_process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._sidecar_process = None
            return False
        return True

    def _wait_for_sidecar(self):
        deadline = time.monotonic() + max(0.0, self.startup_timeout)
        while time.monotonic() < deadline:
            if self._sidecar_process is not None and self._sidecar_process.poll() is not None:
                return False
            try:
                payload = self._health_request()
            except (urllib.error.URLError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
            return isinstance(payload, dict) and payload.get("status") == "ok"
        return False

    @staticmethod
    def _is_connection_refused(exc):
        reason = getattr(exc, "reason", None)
        return (isinstance(reason, ConnectionRefusedError) or
                getattr(reason, "errno", None) == errno.ECONNREFUSED)

    def _unavailable_message(self, exc):
        model_hint = (
            " Set LAYA_MODEL_PATH to the downloaded checkpoint, then retry."
            if not setting("model_path")
            else " Check that the local sidecar can load the checkpoint."
        )
        return f"Laya sidecar unavailable at {self.url}: {exc}.{model_hint}"

    def _post(self, payload):
        request = urllib.request.Request(
            self.url + "/v1/decide",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        for attempt in range(_MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as result:
                    if result.status != 200:
                        raise RuntimeError(f"Laya sidecar returned HTTP {result.status}")
                    response = json.loads(result.read())
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace").strip()
                detail = body or str(exc.reason)
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict) and parsed.get("error"):
                        detail = str(parsed["error"])
                except json.JSONDecodeError:
                    pass
                if exc.code >= 500 and attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_DELAY_S)
                    continue
                raise RuntimeError(
                    f"Laya sidecar unavailable or malformed: HTTP Error {exc.code}: {detail}"
                ) from exc
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                if (isinstance(exc, urllib.error.URLError)
                        and attempt + 1 == _MAX_ATTEMPTS
                        and self._is_connection_refused(exc)
                        and self._start_local_sidecar()
                        and self._wait_for_sidecar()):
                    return self._post(payload)
                if attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_DELAY_S)
                    continue
                raise RuntimeError(f"Laya sidecar unavailable or malformed: {exc}") from exc
        if not isinstance(response, dict):
            raise ValueError("Laya response must be an object")
        return response
