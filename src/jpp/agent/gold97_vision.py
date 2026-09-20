"""Optional, bounded Luna screen transcription; Luna never chooses controls."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


class LunaScreenReader:
    def __init__(self, model=None, timeout=30):
        self.model = model or os.environ.get("CODEX_MODEL", "gpt-5.6-luna")
        self.timeout = timeout

    def describe(self, frame):
        import pygame

        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="jpp-screen-") as directory:
            path = Path(directory) / "screen.png"
            schema = Path(directory) / "screen.schema.json"
            schema.write_text(json.dumps({
                "type": "object", "additionalProperties": False,
                "properties": {
                    "screen_text": {"type": "array", "items": {"type": "string"}},
                    "mode": {"type": "string", "enum": ["battle", "menu", "dialogue",
                                                      "overworld", "unknown"]},
                    "uncertainty": {"type": "string"},
                },
                "required": ["screen_text", "mode", "uncertainty"],
            }))
            image = pygame.surfarray.make_surface(frame.swapaxes(0, 1)[:, :, :3])
            pygame.image.save(image, str(path))
            prompt = (
                "Describe only the visible Game Boy screen. Return a JSON object with "
                "screen_text (array of literal visible text lines), mode (battle, menu, "
                "dialogue, overworld, or unknown), and uncertainty (short text). "
                "Do not choose an action, infer hidden game state, or run tools."
            )
            result = subprocess.run(
                ["codex", "exec", "--ephemeral", "--json", "--sandbox", "read-only",
                 "--output-schema", str(schema),
                 "--model", self.model, "--image", str(path)],
                input=prompt, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Luna screen reading failed")
        usage = {}
        value = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
                usage.update(_usage(event))
                content = event.get("item", {}).get("text", "")
                if event.get("type") == "turn.completed":
                    content = event.get("final_response", content)
                candidate = json.loads(content) if isinstance(content, str) else content
            except (ValueError, TypeError, AttributeError):
                continue
            if (isinstance(candidate, dict) and candidate.get("mode") in
                    {"battle", "menu", "dialogue", "overworld", "unknown"}
                    and isinstance(candidate.get("screen_text"), list)
                    and all(isinstance(item, str) for item in candidate["screen_text"])):
                value = candidate
                continue
        if value is not None:
            usage["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            return {"mode": value["mode"],
                    "screen_text": value["screen_text"][:12],
                    "uncertainty": str(value.get("uncertainty", ""))[:120],
                    "usage": usage}
        raise ValueError("Luna returned no valid screen description")


def _usage(event):
    """Extract usage from the Codex JSON event variants without requiring billing."""
    if not isinstance(event, dict):
        return {}
    raw = event.get("usage") or event.get("response", {}).get("usage")
    if not isinstance(raw, dict):
        raw = event.get("item", {}).get("usage")
    if not isinstance(raw, dict):
        return {}
    input_tokens = raw.get("input_tokens", raw.get("prompt_tokens"))
    output_tokens = raw.get("output_tokens", raw.get("completion_tokens"))
    result = {}
    if input_tokens is not None:
        result["input_tokens"] = input_tokens
    if output_tokens is not None:
        result["output_tokens"] = output_tokens
    if raw.get("total_tokens") is not None:
        result["total_tokens"] = raw["total_tokens"]
    if raw.get("actual_cost_usd", raw.get("cost_usd")) is not None:
        result["actual_cost_usd"] = raw.get("actual_cost_usd", raw.get("cost_usd"))
    return result
