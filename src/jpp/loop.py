"""The tick loop: advance the emulator, decode, classify, press or ask Jev.

The emulator is duck-typed. Anything with `memory`, `game_area_collision()`, `button()`
and `tick()` works, which is PyBoy and also the fake in `tests/test_loop.py`, so the whole
loop is testable without a ROM.
"""

import json
import time
from pathlib import Path

from . import goals, options, route, symbols as S
from .decode import decode
from .options import Branch
from .policy import Decision, Policy

FRAMES_PER_TICK = 8  # one decode per 8 frames, ~7.5 decodes a second at 60 fps
PRESS_FRAMES = 4
NO_PROGRESS_CAP = 40  # decisions per goal before code takes over, CONTEXT section 3


def input_ready(state) -> bool:
    """Whether the game will honour a button this tick.

    Best guess from two `wram.asm` labels: `wJoyIgnore` ("Set buttons are ignored") and
    `wWalkCounter` ("walk animation counter"), which is nonzero mid-step. This predicate
    is the one thing in the project that cannot be settled without a ROM: run
    `jpp probe --rom <path>`, press buttons by hand, and keep the combination that flips
    exactly when input starts being honoured.
    """
    return state.joy_ignore == 0 and state.walk_counter == 0


class BattleLatch:
    """`wBattleResult` only means anything just after a battle ends.

    So latch it on the tick `wIsInBattle` goes nonzero to zero, and never read it on a
    goal-check tick. The previous value (1 wild, 2 trainer, $FF lost) does not matter,
    only the flip to 0. Unset means "no battle has finished", so goal predicates that
    depend on it fail closed.
    """

    WIN, LOSE, DRAW = 0x00, 0x01, 0x02

    def __init__(self):
        self.previous = 0
        self.result: int | None = None
        self.count = 0

    def update(self, is_in_battle: int, battle_result: int) -> int | None:
        if self.previous != 0 and is_in_battle == 0:
            self.result = battle_result
            self.count += 1
        self.previous = is_in_battle
        return self.result


class Driver:
    """Emulator plus the decoded snapshot, one tick at a time."""

    def __init__(self, emulator):
        self.emu = emulator
        self.latch = BattleLatch()
        self.state = None
        self.turn = 0  # turns inside the current battle, reset when one ends

    def tick(self, frames: int = FRAMES_PER_TICK):
        self.emu.tick(frames)
        self.state = decode(self.emu.memory)
        before = self.latch.count
        self.latch.update(
            self.emu.memory[S.IS_IN_BATTLE], self.emu.memory[S.BATTLE_RESULT]
        )
        if self.latch.count != before:
            self.turn = 0
        return self.state

    def press(self, button: str):
        self.emu.button(button, PRESS_FRAMES)
        return self.tick()

    def collision(self):
        return self.emu.game_area_collision()


def probe(emulator, ticks: int, out=print, every: int = 8):
    """Print the decoded state and the input-readiness candidates once a second.

    Task 2's discovery tool: walk the route by hand while this runs, and read off both
    the waypoint tiles and which byte combination gates input.
    """
    driver = Driver(emulator)
    for i in range(ticks):
        st = driver.tick()
        if i % every:
            continue
        out(
            f"map={st.map_name}(${st.map_id:02X}) pos=({st.x},{st.y}) "
            f"battle={st.battle.kind} last_battle_result={driver.latch.result} "
            f"party={len(st.party)} | joy_ignore=${st.joy_ignore:02X} "
            f"walk_counter={st.walk_counter} text_box_id=${st.text_box_id:02X} "
            f"font_loaded={st.font_loaded} tile_in_front=${st.tile_in_front:02X} "
            f"menu={st.menu_item}/{st.max_menu_item} ready={input_ready(st)}"
        )
    return driver


def classify(driver: Driver, goal, waypoint) -> tuple[str, object]:
    """Code decides what kind of tick this is. Only two answers reach Jev.

    Returns (action, payload): ("wait", None), ("press", button), or ("branch", Branch).
    """
    st = driver.state
    if not input_ready(st):
        return "wait", None
    if st.in_battle:
        if st.max_menu_item > 0 or st.menu_item > 0:
            branch = options.battle_branch(
                st, goal, items=options.bag(driver.emu.memory), turn=driver.turn
            )
            return "branch", branch
        return "press", "a"
    if st.text_box_id:
        return "press", "a"  # a text box with no cursor: A costs nothing
    step = route.next_step(st, waypoint)
    if step:
        return "press", step
    free = route.sidesteps(st, driver.collision(), waypoint)
    if len(free) == 1:
        return "press", free[0]
    if len(free) > 1:
        return "branch", options.tie_branch(st, goal, waypoint, free)
    return "press", "a"


def play(
    emulator,
    policy: Policy,
    max_decisions: int,
    log_path: Path | None = None,
    on_decision=None,
    max_ticks: int = 200_000,
) -> list[dict]:
    """Run until the goal stack empties or `max_decisions` Jev calls have happened."""
    driver = Driver(emulator)
    stack = goals.GoalStack()
    records: list[dict] = []
    log = log_path.open("a") if log_path else None
    stale, on_goal = 0, None
    try:
        for _ in range(max_ticks):
            if len(records) >= max_decisions or stack.done:
                break
            driver.tick()
            stack.advance(driver.state, driver.latch)
            goal = stack.current
            if goal is None:
                break
            if goal is not on_goal:
                on_goal, stale = goal, 0
            waypoint = route.waypoint_for(goal, driver.state)
            action, payload = classify(driver, goal, waypoint)
            if action == "wait":
                continue
            if action == "press":
                driver.press(payload)
                continue
            forced = stale >= NO_PROGRESS_CAP
            decision = policy.decide(payload, forced=forced)
            driver.turn += payload.kind == "battle"
            for button in options.buttons_for(driver.state, payload, decision.option):
                driver.press(button)
            record = _record(goal, payload, decision, driver)
            records.append(record)
            if log:
                log.write(json.dumps(record) + "\n")
                log.flush()
            if on_decision:
                on_decision(record)
            stale += 1
    finally:
        if log:
            log.close()
    return records


def _record(goal, branch: Branch, decision: Decision, driver: Driver) -> dict:
    st = driver.state
    return {
        "t": time.time(),
        "goal": goal.name,
        "battle_index": driver.latch.count,
        "kind": branch.kind,
        "state": branch.state,
        "options": branch.options,
        "choice": decision.option,
        "probabilities": decision.probabilities,
        "nouls": decision.nouls,
        "fell_back": decision.fell_back,
        "latency_ms": decision.latency_ms,
        "input_tokens": decision.input_tokens,
        "active_hp_fraction": st.battle.active.hp_fraction
        if st.battle.active
        else None,
    }
