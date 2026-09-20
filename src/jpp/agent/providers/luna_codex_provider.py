"""Codex CLI provider. Uses ChatGPT-authenticated `codex exec`, never browser tokens."""

import json
import os
import subprocess


class LunaCodexProvider:
    def __init__(self, model=None, timeout=30):
        self.model = model or os.environ.get("CODEX_MODEL", "gpt-5.6-luna")
        self.timeout = timeout

    def _ask(self, task, payload):
        prompt = (
            "You are Luna, an autonomous Game Boy game agent. The cartridge may be "
            "Pokémon Red, Gold 97 Reforged, or another supported game. Return JSON only. "
            "Choose from supplied allowlisted actions. Never output buttons or shell commands.\n"
            f"Task: {task}\nPayload: {json.dumps(payload, separators=(',', ':'))}"
        )
        result = subprocess.run(
            ["codex", "exec", "--json", "--model", self.model, prompt],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "codex exec failed")
        usage = {}
        value = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage.update(_usage(event))
            if isinstance(event, dict) and isinstance(event.get("action"), str):
                value = event
        if value is None:
            raise ValueError("Codex returned no JSON action")
        value = dict(value)
        value.update(usage)
        return value

    def decide_tactical(self, state, options):
        answer = self._ask("pick one tactical action", {"state": state, "options": options})
        if answer.get("action") not in options:
            raise ValueError("provider action outside allowlist")
        return answer

    def decide_strategy(self, state, memory):
        return self._ask("choose one strategic objective", {"state": state, "memory": memory[-8:]})

    def recover(self, state, history):
        answer = self._ask("choose safe recovery action", {"state": state, "history": history[-12:]})
        if answer.get("action") not in {"replan", "reload_checkpoint", "wait"}:
            raise ValueError("recovery action outside allowlist")
        return answer

    def generate_commentary(self, event):
        try:
            return self._ask("write one short public thought", {"event": event}).get(
                "commentary", "Jev is thinking."
            )[:180]
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            return "Jev is resting while decision service recovers."


def _usage(event):
    if not isinstance(event, dict):
        return {}
    raw = event.get("usage") or event.get("response", {}).get("usage")
    if not isinstance(raw, dict):
        raw = event.get("item", {}).get("usage")
    if not isinstance(raw, dict):
        return {}
    result = {}
    for output, names in {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
        "actual_cost_usd": ("actual_cost_usd", "cost_usd"),
    }.items():
        for name in names:
            if raw.get(name) is not None:
                result[output] = raw[name]
                break
    return result
