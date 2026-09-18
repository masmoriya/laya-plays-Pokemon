"""The only place that talks to Jev, and the only place that can be wrong for free.

One request per branch, fan-out style: the choice over the legal options plus the two
nouls, in one body, for one request's price. Every answer is checked against the
enumerated option set before a button is pressed, and anything that fails, times out, or
comes back unrecognised takes the code default. Jev makes this agent pickier, never
looser.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://api.typesafe.ai"
PATH = "/v1/systemone"
MODEL = "jev-1.13.0"  # pinned: the Brier number is a published claim
TIMEOUT_S = 8.0
RETRY_STATUS = (429, 500, 502, 503, 504, 529)
PRICE_PER_INPUT_TOKEN = 0.042 / 1e6

CHOICE_INSTRUCTIONS = (
    "Given the goal and the state, which of these actions should the player take next? "
    "Judge only this decision, not the rest of the game."
)
FAINTS_INSTRUCTIONS = (
    "If the player takes the action you chose, will the player's active Pokemon be "
    "knocked out before the player gets another turn? True: its HP reaches zero this "
    "turn. False: it is still conscious when the next action is chosen."
)
FLEE_INSTRUCTIONS = (
    "Is the player's position in this battle bad enough that leaving is better than "
    "continuing? True: continuing risks losing the whole party. False: the player can "
    "still win or safely trade turns."
)


@dataclass
class Decision:
    option: str
    probabilities: dict = field(default_factory=dict)
    confidence: float | None = None
    nouls: dict = field(default_factory=dict)
    fell_back: bool = False
    reason: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    model: str = MODEL


def cache_key(state, questions) -> str:
    blob = json.dumps({"state": state, "questions": questions}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def questions_for(branch) -> dict:
    criteria = dict(branch.options)
    criteria["other"] = None  # escape hatch; maps to the code default, not an error
    questions = {
        "next_action": {
            "type": "choice",
            "instructions": CHOICE_INSTRUCTIONS,
            "criteria": criteria,
        }
    }
    if branch.kind == "battle":
        questions["faints_this_turn"] = {
            "type": "noul",
            "instructions": FAINTS_INSTRUCTIONS,
        }
        questions["should_flee"] = {"type": "noul", "instructions": FLEE_INSTRUCTIONS}
    return questions


class JevClient:
    """Direct wire format. Also the replay and record halves of CONTEXT section 5."""

    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=MODEL,
        timeout=TIMEOUT_S,
        replay_dir=None,
        record_dir=None,
        retries=1,
    ):
        self.base_url = (
            base_url or os.environ.get("JEV_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
        self.model = model
        self.timeout = timeout
        self.replay_dir = Path(replay_dir) if replay_dir else None
        self.record_dir = Path(record_dir) if record_dir else None
        self.retries = retries
        self.last_attempts = 0  # retries on the last call; a retried call is not timed

    def ask(self, state, questions) -> dict:
        key = cache_key(state, questions)
        if self.replay_dir:
            cassette = self.replay_dir / f"{key}.json"
            if cassette.exists():
                return json.loads(cassette.read_text())
            raise KeyError(f"no recorded answer for {key}")
        body = json.dumps(
            {"model": self.model, "state": state, "questions": questions}
        ).encode()
        deadline = time.monotonic() + self.timeout
        self.last_attempts = 0
        started = time.monotonic()
        payload = self._post(body, deadline)
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            # a cassette keeps its own latency, but only when nothing was retried, so a
            # replayed run reports the call and not the backoff
            kept = payload | {
                "_latency_ms": round((time.monotonic() - started) * 1000, 1)
                if not self.last_attempts
                else None
            }
            (self.record_dir / f"{key}.json").write_text(json.dumps(kept, indent=1))
        return payload

    def _post(self, body: bytes, deadline: float, attempt: int = 0) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.base_url + PATH, data=body, headers=headers
        )
        try:
            with urllib.request.urlopen(
                request, timeout=max(0.1, deadline - time.monotonic())
            ) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # backoff only on 429 and 5xx; a 400 or 422 is our bug and retrying hides it
            if e.code in RETRY_STATUS and attempt < self.retries and time.monotonic() < deadline:
                wait = _retry_after(e.headers) or 0.5
                if time.monotonic() + wait < deadline:
                    time.sleep(wait)
                    self.last_attempts = attempt + 1
                    return self._post(body, deadline, attempt + 1)
            raise


def _retry_after(headers) -> float | None:
    """`retry-after` in seconds, or `retry-after-ms`, whichever the endpoint sends."""
    for name, scale in (("retry-after", 1.0), ("retry-after-ms", 0.001)):
        raw = headers.get(name)
        if raw:
            try:
                return float(raw) * scale
            except ValueError:
                return None
    return None


def default_option(branch) -> tuple[str, str]:
    """The code's own answer: what happens with no Jev, a bad Jev, or no network."""
    options = branch.options
    if branch.kind == "battle":
        ranked = [k for k in options if k.startswith("use_move_")]
        if ranked:
            best = max(ranked, key=lambda k: _move_rank(options[k]))
            return best, "highest-effectiveness move"
    return sorted(options)[0], "first option in sorted order"


def _move_rank(description: str) -> int:
    for word, rank in (
        ("super effective", 3),
        ("neutral", 2),
        ("not very effective", 1),
    ):
        if word in description:
            return rank
    return 0


class Policy:
    def __init__(self, client: JevClient | None = None, enabled: bool = True):
        self.client = client or JevClient()
        self.enabled = enabled

    def decide(self, branch, forced: bool = False) -> Decision:
        fallback, why = default_option(branch)
        if forced or not self.enabled:
            return Decision(
                option=fallback,
                fell_back=True,
                reason="no progress cap reached" if forced else "jev disabled",
            )
        questions = questions_for(branch)
        started = time.monotonic()
        try:
            payload = self.client.ask(branch.state, questions)
        except Exception as e:  # any failure falls back to the tool's no-Jev behaviour
            return Decision(
                option=fallback,
                fell_back=True,
                reason=f"{type(e).__name__}: {e}",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        answers = payload.get("answers", {})
        choice = answers.get("next_action", {})
        option = choice.get("choice")
        probabilities = choice.get("probabilities", {})
        nouls = {
            name: a["noul"] for name, a in answers.items() if a.get("type") == "noul"
        }
        usage = payload.get("usage") or {}
        common = dict(
            probabilities=probabilities,
            confidence=choice.get("confidence"),
            nouls=nouls,
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens") or 0,
            model=payload.get("model", self.client.model),
        )
        if option not in branch.options:
            return Decision(
                option=fallback,
                fell_back=True,
                reason=f"unusable option {option!r}, took the {why}",
                **common,
            )
        return Decision(option=option, **common)


def cost_usd(input_tokens: int) -> float:
    return input_tokens * PRICE_PER_INPUT_TOKEN
