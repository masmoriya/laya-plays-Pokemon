"""Small OpenAI-compatible client for the local Qwen vision server."""

import base64
import json
import os
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from PIL import Image

DEFAULT_BASE_URL = "http://127.0.0.1:8767/v1"
DEFAULT_MODEL = "mlx-community/Qwen3-VL-4B-Instruct-4bit"


def image_url(image):
    """Encode a bounded PNG data URL without exposing a local file path."""
    image = image.convert("RGB")
    if image.size == (160, 144):
        image = image.resize((480, 432), Image.Resampling.NEAREST)
    image.thumbnail((640, 576))
    data = BytesIO()
    image.save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()


class LocalModelClient:
    """Talk to local Qwen through its OpenAI-compatible HTTP surface."""

    def __init__(self, base_url=None, model=None, api_key=None, timeout=120):
        self.base_url = (
            base_url or os.environ.get("LAYA_VLM_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("LAYA_VLM_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("LAYA_VLM_API_KEY")
        self.timeout = timeout
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP model endpoint without embedded credentials")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            if parsed.scheme != "https" or not self.api_key:
                raise ValueError("Remote model endpoints require HTTPS and LAYA_VLM_API_KEY")
        self._opener = build_opener(ProxyHandler({}))

    def _request(self, path, payload=None, timeout=None):
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
            method = "POST"
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}", data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=timeout or self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Qwen server returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Qwen server unavailable or malformed: {exc}") from exc

    def health(self):
        response = self._request("models", timeout=3)
        models = [item.get("id") for item in response.get("data", ())]
        if self.model not in models:
            raise RuntimeError(f"Load the configured Qwen model in the server: {self.model}")
        return {"status": "ok", "model": self.model, "base_url": self.base_url}

    def structured(self, messages, schema, max_tokens=1024):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            },
        }
        result = self._request("chat/completions", payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Qwen returned no completion choice")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise RuntimeError("Qwen returned an invalid completion choice")
        if choice.get("finish_reason") == "length":
            raise RuntimeError("Qwen output was truncated; no result was accepted")
        try:
            value = json.loads(choice["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Qwen returned no valid structured result") from exc
        usage = result.get("usage") or {}
        incoming = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        outgoing = usage.get("completion_tokens", usage.get("output_tokens", 0))
        return value, {"input_tokens": incoming, "output_tokens": outgoing,
                       "total_tokens": usage.get("total_tokens", (incoming or 0) + (outgoing or 0))}
