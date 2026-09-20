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
        for line in reversed(result.stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("action"), str):
                return value
        raise ValueError("Codex returned no JSON action")

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
