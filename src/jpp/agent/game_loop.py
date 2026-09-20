"""Adapter-neutral agent loop for cartridges without a route-specific planner.

The Red loop has detailed Gen 1 menu and map knowledge. Other adapters still get a
useful closed-set control loop: Luna sees the adapter's verified snapshot and can only
choose one of the ordinary Game Boy controls.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

FRAMES_PER_DECISION = 8
PRESS_FRAMES = 4
BUTTON_OPTIONS = {
    "a": "press A",
    "b": "press B",
    "down": "move down",
    "left": "move left",
    "right": "move right",
    "start": "press Start",
    "up": "move up",
    "select": "press Select",
    "wait": "wait for the game to advance",
}


@dataclass(frozen=True)
class GenericBranch:
    kind: str
    state: dict
    options: dict


def _mon(mon):
    if not mon:
        return None
    return {
        "slot": getattr(mon, "slot", None),
        "species": getattr(mon, "species", "UNKNOWN"),
        "level": getattr(mon, "level", None),
        "hp": getattr(mon, "hp", None),
        "max_hp": getattr(mon, "max_hp", None),
        "status": getattr(mon, "status", None),
    }


def _state(snapshot):
    state = snapshot.state
    species = getattr(state, "pokedex_species", ())
    dex_total = len(species) - 1 if species and species[0] == "UNKNOWN" else len(species)
    battle = getattr(state, "battle", None)
    body = {
        "game": snapshot.title,
        "map": getattr(state, "map_name", snapshot.title),
        "position": {
            "x": getattr(state, "x", None),
            "y": getattr(state, "y", None),
        },
        "in_battle": bool(getattr(state, "in_battle", False)),
        "party": [_mon(mon) for mon in getattr(state, "party", ())],
        "badges": list(getattr(state, "badge_ids", ())),
        "badge_total": getattr(state, "badge_total", None),
        "pokedex": {
            "caught": len(getattr(state, "pokedex_caught_ids", ())),
            "seen": len(getattr(state, "pokedex_seen_ids", ())),
            "total": max(0, dex_total),
        },
        "actions": BUTTON_OPTIONS,
    }
    if battle:
        body["battle"] = {
            "kind": getattr(battle, "kind", "none"),
            "active": _mon(getattr(battle, "active", None)),
            "opponent": _mon(getattr(battle, "opponent", None)),
        }
    return body


def _advance(emulator, frames, on_frame, on_audio=None):
    if on_frame is None and on_audio is None:
        emulator.tick(frames)
        return
    for _ in range(frames):
        emulator.tick(1)
        if on_audio is not None:
            on_audio(emulator)
        if on_frame is not None:
            on_frame(emulator)


def play(emulator, adapter, agent_policy, max_decisions, log_path=None,
         on_decision=None, on_frame=None, on_audio=None, run_id="headless-gold97",
         memory_state=None, memory_state_out=None):
    """Run an adapter snapshot through a safe, game-neutral button policy."""
    from ..gold97_adapter import Gold97Adapter

    if isinstance(adapter, Gold97Adapter):
        from .gold97_play import play_gold97
        return play_gold97(emulator, adapter, agent_policy, max_decisions,
                           log_path, on_decision, on_frame, on_audio,
                           run_id=run_id, memory_state=memory_state,
                           memory_state_out=memory_state_out)
    records = []
    log = Path(log_path).open("a") if log_path else None
    try:
        for index in range(max_decisions):
            snapshot = adapter.snapshot(emulator)
            body = _state(snapshot)
            branch = GenericBranch("generic", body, BUTTON_OPTIONS)
            decision = agent_policy.decide(branch)
            if decision.option != "wait":
                emulator.button(decision.option, PRESS_FRAMES)
            _advance(emulator, FRAMES_PER_DECISION, on_frame, on_audio)
            record = {
                "t": time.time(),
                "goal": f"explore {snapshot.title}",
                "kind": "generic",
                "battle_index": 0,
                "state": body,
                "options": BUTTON_OPTIONS,
                "choice": decision.option,
                "probabilities": decision.probabilities,
                "nouls": decision.nouls,
                "fell_back": decision.fell_back,
                "reason": decision.reason,
                "latency_ms": decision.latency_ms,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "total_tokens": decision.total_tokens,
                "actual_cost_usd": decision.actual_cost_usd,
                "active_hp_fraction": None,
                "active_slot": None,
                "decision": index + 1,
            }
            records.append(record)
            if log:
                log.write(json.dumps(record) + "\n")
                log.flush()
            if on_decision:
                on_decision(record)
    finally:
        if log:
            log.close()
    return records
