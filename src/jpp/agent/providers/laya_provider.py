"""Local Laya sidecar client for closed-set tactical decisions."""

import json
import math
import os
import time
import urllib.error
import urllib.request


DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT_S = 3.0
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
        self.url = (url or os.environ.get("LAYA_BASE_URL") or DEFAULT_URL).rstrip("/")
        self.timeout = float(timeout or os.environ.get("LAYA_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
        self.min_confidence = float(
            min_confidence
            if min_confidence is not None
            else os.environ.get("LAYA_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
        )
        if not math.isfinite(self.min_confidence) or not 0 <= self.min_confidence <= 1:
            raise ValueError("LAYA_MIN_CONFIDENCE must be between 0 and 1")
        self.model = "laya-local"

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
        }

    def decide_strategy(self, state, memory):
        return {"objective": state.get("objective", "Continue current route")}

    def recover(self, state, history):
        return {"action": "replan", "commentary": "Route stalled; replanning."}

    def generate_commentary(self, event):
        return event.get("commentary", "Laya is deciding.")

    def health(self):
        request = urllib.request.Request(self.url + "/health", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as result:
                return json.loads(result.read())
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Laya sidecar unavailable: {exc}") from exc

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
                if attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_DELAY_S)
                    continue
                raise RuntimeError(f"Laya sidecar unavailable or malformed: {exc}") from exc
        if not isinstance(response, dict):
            raise ValueError("Laya response must be an object")
        return response
