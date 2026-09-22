"""Structured live-dashboard state without inventing private model reasoning."""

from collections import deque
from copy import deepcopy
from time import time


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return str(value)


class LiveAgentState:
    """Own the small, honest projection rendered by the live dashboard."""

    def __init__(self, memory):
        self.memory = memory
        self.sequence = 0
        self.current = {
            "sequence": 0,
            "kind": "idle",
            "source": "",
            "why": "Waiting for a decision",
            "action": "No action yet",
            "result": "",
        }
        self.decisions = deque(maxlen=8)
        previous = [item for item in memory.experience.recent(200)
                    if item.get("kind") == "model_call"]
        self.calls = deque(reversed(previous[:40]), maxlen=40)
        self.inputs = {}
        self.vision = None

    def decide(self, *, kind, source, why, action):
        self.sequence += 1
        self.current = {
            "sequence": self.sequence,
            "kind": str(kind),
            "source": str(source),
            "why": str(why or "Current game state"),
            "action": str(action or "Wait"),
            "result": "Waiting for result",
        }
        self.decisions.append(dict(self.current))

    def result(self, value):
        if not value or not self.current.get("sequence"):
            return
        self.current["result"] = str(value)
        if self.decisions and self.decisions[-1]["sequence"] == self.current["sequence"]:
            self.decisions[-1] = dict(self.current)

    def model_call(self, provider, usage=None, model_input=None, *, confidence=None,
                   status="completed", error="", phase="tactical", fallback=""):
        usage = usage or {}
        model_input = model_input or {}
        if model_input:
            self.inputs[str(provider).lower()] = deepcopy(model_input)
        context = model_input.get("context") or {}
        sample = {
            "provider": str(provider).lower(),
            "phase": phase,
            "timestamp": time(),
            "status": status,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "latency_ms": round(float(usage.get("latency_ms") or 0), 1),
            "confidence": (float(confidence) if isinstance(confidence, (int, float))
                           and not isinstance(confidence, bool) else None),
            "budget": context.get("budget"),
            "retained_tokens": context.get("retained_tokens"),
            "submitted_tokens": context.get("submitted_tokens"),
            "omitted_fields": list(context.get("omitted_fields") or ()),
            "error": str(error)[:180],
            "fallback": str(fallback)[:80],
        }
        self.calls.append(sample)
        self.memory.experience.record("model_call", **sample)

    def vision_started(self, frame, model_input):
        self.vision = {
            "frame": frame.copy(),
            "model_input": deepcopy(model_input),
            "status": "analyzing",
            "result": None,
            "error": "",
            "timestamp": time(),
        }

    def vision_finished(self, result=None, error=""):
        if self.vision is None:
            return
        self.vision["status"] = "error" if error else "completed"
        self.vision["result"] = _plain(result)
        self.vision["error"] = str(error)[:180]

    def snapshot(self):
        return {
            "decision": dict(self.current),
            "decisions": [dict(item) for item in reversed(self.decisions)],
            "model_calls": [dict(item) for item in self.calls],
            "model_inputs": deepcopy(self.inputs),
            "vision": self.vision,
        }


def display_action(action, description=""):
    labels = {
        "up": "Move up", "down": "Move down", "left": "Move left",
        "right": "Move right", "a": "Press A", "b": "Press B",
        "start": "Press Start", "select": "Press Select", "wait": "Wait",
    }
    return labels.get(action, str(description or action).replace("_", " ").title())


def battle_action_text(state, action):
    active = getattr(getattr(state, "battle", None), "active", None)
    active_name = getattr(active, "species", "Active Pokémon").title()
    party = tuple(getattr(state, "party", ()) or ())
    target = action.target
    if action.kind == "switch" and target is not None and target < len(party):
        return f"Switch {active_name} to {party[target].species.title()}"
    if action.kind == "move" and target is not None:
        moves = tuple(getattr(active, "moves", ()) or ())
        if target < len(moves):
            return f"Use {str(moves[target]).replace('_', ' ').title()}"
    if action.kind == "heal":
        return f"Heal {active_name}"
    if action.kind == "ball":
        foe = getattr(getattr(state, "battle", None), "opponent", None)
        return f"Throw a Poké Ball at {getattr(foe, 'species', 'the opponent').title()}"
    return {
        "escape": "Run from the encounter", "stay": f"Keep {active_name} in",
        "struggle": "Use Struggle", "wait": "Wait for battle state",
    }.get(action.kind, action.kind.replace("_", " ").title())


def short_reason(reason):
    value = str(reason or "Current game state")
    if ":" in value:
        value = value.split(":", 1)[1].strip()
    replacements = {
        "best nominal damage; modifiers uncertain": "Best estimated damage; modifiers uncertain",
        "survive incoming attack": "Survive the next hit",
        "healthy replacement": "Use a healthy replacement",
        "safer matchup": "Create a safer matchup",
        "likely knockout": "Likely knockout",
    }
    return replacements.get(value.casefold(), value[:120].capitalize())
