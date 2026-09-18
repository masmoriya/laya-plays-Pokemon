"""Build `fixtures/runs/sample.jsonl` so `measure` and the overlay work on a fresh clone.

Forty decisions over synthetic RAM: five short battles and ten overworld ties and
dialogues. Each one is sent to a real Jev if one is reachable, and the answer is cached in
`fixtures/recorded/`, so re-running this costs nothing. When the endpoint is unreachable
or rate-limited the row falls back to a deterministic stand-in and is tagged
`"source": "fake"`, which `measure` counts and prints. No row is ever a hand-picked
number.

    JEV_BASE_URL=http://127.0.0.1:4322 uv run python fixtures/make_run.py
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import jaggedness  # noqa: E402
import make_ram  # noqa: E402

from jpp import options, policy, symbols as S  # noqa: E402
from jpp.decode import decode  # noqa: E402
from jpp.goals import GOALS  # noqa: E402

HERE = Path(__file__).parent
RECORDED = HERE / "recorded"
OUT = HERE / "runs" / "sample.jsonl"
GAP = float(os.environ.get("JEV_GAP_S", "1"))
OFFLINE = os.environ.get("JEV_OFFLINE") == "1"
DEADLINE_S = float(os.environ.get("JEV_DEADLINE_S", "120"))

WALK_GOAL = next(g for g in GOALS if g.name == "get_starter")
# five battles of six turns: active HP down to a faint in three of them
BATTLES = (
    (19, 16, 13, 11, 8, 5),
    (19, 15, 10, 6, 3, 0),
    (18, 14, 12, 9, 7, 4),
    (17, 12, 8, 5, 2, 0),
    (19, 16, 11, 7, 3, 0),
)
FOE_HP = (21, 18, 15, 11, 7, 3)


def battle_branches():
    for battle_index, series in enumerate(BATTLES, start=1):
        for turn, hp in enumerate(series, start=1):
            ram = make_ram.battle(active_hp=hp, foe_hp=FOE_HP[turn - 1])
            state = decode(bytes(ram))
            branch = options.battle_branch(state, jaggedness.BATTLE_GOAL, turn=turn)
            yield battle_index, state, branch


def walk_branches():
    for i in range(10):
        ram = make_ram.overworld()
        ram[S.X_COORD], ram[S.Y_COORD] = 8 + i % 4, 6 + i % 3
        state = decode(bytes(ram))
        if i % 3 == 2:
            branch = options.dialogue_branch(
                state,
                WALK_GOAL,
                "OAK: Wait! Don't go into the tall grass!",
                ["YES", "NO"],
            )
        else:
            branch = options.tie_branch(
                state,
                WALK_GOAL,
                (12, 11),
                ["down", "right"] if i % 2 else ["down", "left"],
            )
        yield 0, state, branch


def interleave():
    """Ties and dialogues spread through the battles, the way a run actually goes."""
    battles, walks = list(battle_branches()), list(walk_branches())
    out = []
    for i, item in enumerate(battles):
        out.append(item)
        if i % 3 == 2 and walks:
            out.append(walks.pop(0))
    return out + walks


def stand_in(branch) -> dict:
    """A deterministic answer for rows a real endpoint would not serve.

    Derived from the request hash, not chosen by hand, and every row it produces is
    tagged `"source": "fake"` so no number here can be mistaken for a measurement.
    """
    seed = int(
        hashlib.sha256(json.dumps(branch.state, sort_keys=True).encode()).hexdigest(),
        16,
    )
    keys = list(branch.options) + ["other"]
    weights = [((seed >> (7 * i)) % 900) + 100 for i in range(len(keys))]
    total = sum(weights)
    probabilities = {k: round(w / total, 3) for k, w in zip(keys, weights)}
    choice = max(probabilities, key=probabilities.get)
    answers = {
        "next_action": {
            "type": "choice",
            "choice": choice,
            "confidence": probabilities[choice],
            "probabilities": probabilities,
        }
    }
    if branch.kind == "battle":
        answers["faints_this_turn"] = {
            "type": "noul",
            "noul": round(((seed >> 31) % 1000) / 1000, 3),
        }
        answers["should_flee"] = {
            "type": "noul",
            "noul": round(((seed >> 41) % 1000) / 1000, 3),
        }
    return {"model": "fake", "answers": answers, "usage": {"input_tokens": 0}}


def main():
    client = policy.JevClient(record_dir=RECORDED, timeout=30.0, retries=2)
    rows, real, fake = [], 0, 0
    give_up_at = None
    clock = 0.0
    for battle_index, state, branch in interleave():
        questions = policy.questions_for(branch)
        key = policy.cache_key(branch.state, questions)
        cassette = RECORDED / f"{key}.json"
        source, started, timed = "jev", time.monotonic(), True
        if cassette.exists():
            payload, source = json.loads(cassette.read_text()), "replay"
            timed = bool(payload.get("_latency_ms"))
        elif OFFLINE or (give_up_at and time.monotonic() > give_up_at):
            payload, source, timed = stand_in(branch), "fake", False
        else:
            try:
                time.sleep(GAP)
                started = time.monotonic()
                payload = client.ask(branch.state, questions)
                give_up_at = None
                timed = client.last_attempts == 0  # a retried call timed the backoff
            except Exception as e:
                print(f"  {type(e).__name__}: {e}", flush=True)
                give_up_at = give_up_at or time.monotonic() + DEADLINE_S
                payload, source, timed = stand_in(branch), "fake", False
        latency_ms = payload.get("_latency_ms") or round(
            (time.monotonic() - started) * 1000, 1
        )
        answers = payload["answers"]
        choice = answers["next_action"]
        real, fake = real + (source != "fake"), fake + (source == "fake")
        if timed:
            clock += latency_ms / 1000  # the only clock this run has: its own call time
        rows.append(
            {
                "t": round(clock, 3),
                "mode": "call-latency-only",
                "goal": branch.state["goal"][:40],
                "battle_index": battle_index,
                "kind": branch.kind,
                "state": branch.state,
                "options": branch.options,
                "choice": choice["choice"]
                if choice["choice"] in branch.options
                else None,
                "probabilities": choice.get("probabilities", {}),
                "nouls": {
                    k: v["noul"] for k, v in answers.items() if v.get("type") == "noul"
                },
                "fell_back": choice["choice"] not in branch.options,
                "latency_ms": latency_ms if timed else None,
                "input_tokens": (payload.get("usage") or {}).get("input_tokens") or 0,
                "active_hp_fraction": state.battle.active.hp_fraction
                if state.in_battle
                else None,
                "source": source,
            }
        )
        print(
            f"{len(rows):3} {branch.kind:9} {source:4} {choice['choice']}", flush=True
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows))
    timed = sum(1 for r in rows if r["latency_ms"])
    print(f"\n{len(rows)} decisions -> {OUT}  ({real} real answers, {fake} stand-in, {timed} timed)")


if __name__ == "__main__":
    main()
