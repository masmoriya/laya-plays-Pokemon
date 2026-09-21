"""Gold 97's closed-set controller shared by live and headless play."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

from .gold97_memory import Gold97Memory
from .gold97_dialogue import DialogueProgress
from .gold97_playback import Playback
from .gold97_training import Training
from .gold97_party import PartyReorder
from .gold97_roster_service import RosterService
from .gold97_rewards import RewardLedger
from .gold97_policy_config import reward_weights
from ..live_map_state import LiveMapState
from .journey_strategy import JourneyStrategy
from .gold97_map_probe import probe_options
from .gold97_items import item_action, is_item_entity, item_cell
from .gold97_navigation import MovementHistory, frontier_step
from .gold97_opening import Gold97Opening, _route
from .gold97_journey_nav import journey_step
from .gold97_battle import Gold97BattleStrategy
from .gold97_battle_executor import BattleExecutor
from .gold97_learning import learning_menu_step, proposed_move
from .gold97_state import decision_state
from .gold97_vision import LunaScreenReader
from .gold97_services import (
    center_retreat_target, center_target, is_center, is_mart,
    mart_target, needs_healing, novel_capture, nurse_target, should_buy_balls,
)
from .gold97_shopping import mart_menu_step
from ..route_progress import MAIN, RouteProgress
from .old_species import hack_exclusive
from .policy_adapter import ProviderPolicy
from .providers.jev_provider import JevProvider
from .usage import UsageTotals


_STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_MOVE_HOLD_FRAMES = 36
_MENU_COOLDOWN_FRAMES = 45
_REVERSE = {"up": "down", "down": "up", "left": "right", "right": "left"}
# The ROM's verified Players House 2F warp is the only map-specific guard here;
# it gets the fresh run out of the starting room without prescribing the story.
_KNOWN_EXITS = {(0x14, 0x07): (7, 1)}
_WAIT_LIMIT = 3
_MAX_CAPTURE_ATTEMPTS = 3


def _visible_prompt(state):
    """A missing overworld view alone does not mean a dialogue is open."""
    lines = getattr(state, "screen_lines", ()) or ()
    return (any(line.strip() for line in lines[12:]) or
            (getattr(state, "screen_cursor", None) is not None and
             any(line.strip() for line in lines)))


class Gold97Controller:
    def __init__(self, run_id, *, database="data/jev.sqlite", policy=None,
                 vision=None, vision_enabled=True, save_encounter=None,
                 restore_encounter=None, restore_stuck=None, strategy_provider=None):
        self.memory = Gold97Memory(run_id, database)
        self.dialogue = DialogueProgress()
        self.playback = Playback(self.memory)
        self.rewards = RewardLedger(self.memory, reward_weights())
        self.map_state = LiveMapState()
        self.training = Training(self.memory)
        self.party_reorder = PartyReorder()
        self.roster_service = RosterService(self)
        self.opening = Gold97Opening()
        self.route = RouteProgress.from_dict(self.memory.world.get("route"))
        self.opening_goal = None
        self.navigation_target = None
        self.policy = policy or ProviderPolicy(JevProvider())
        self.vision = vision if vision is not None else (LunaScreenReader() if vision_enabled else None)
        self.save_encounter = save_encounter
        self.restore_encounter = restore_encounter
        self.restore_stuck = restore_stuck
        self.stuck_restores = 0
        # A slow screen read or health check must not queue walking decisions.
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.vision_future = None
        self.decision_future = None
        self.decision_key = None
        self.vision_key = None
        self.screen_note = None
        self.last = None
        self.cooldown = 0
        self.stalls = 0
        self.movement_history = MovementHistory()
        self.replans_at = {}
        self.unknown_frames = 0
        self.no_options_frames = 0
        self.paused = False
        self.pause_reason = ""
        self.encounter = None
        self.pending_frames = 0
        self.attempts = {}
        self.title_bootstrap_done = False
        self.last_decision = None
        self.latest_model_input = None
        self.last_battle = None
        self.healing = None
        self.recovery = None
        self.shopping = None
        self.shopping_skip = set()
        self.capture = None
        self.wait_streak = 0
        self.terrain = None
        self.usage = UsageTotals()
        self.held_action = None
        self.last_move_direction = None
        self.interaction_positions = set()
        self.interaction_map_key = None
        self.attempted_items = set()
        self.battle_strategy = Gold97BattleStrategy()
        self.battle_executor = BattleExecutor()
        self.wild_battle_committed = False
        self.battle_phase = None
        self.battle_target = None
        self.battle_cursor_index = 0
        self.battle_pp_before = None
        self.battle_foe_hp_before = None
        self.battle_switch_target = None
        self.battle_switch_phase = None
        self.battle_switch_text = None
        self.learning_move = None
        self.provider_health_future = None
        self.provider_health = "unknown"
        self.provider_health_error = ""
        self.provider_health_checked_at = monotonic()
        self.provider_events = deque(maxlen=500)
        self.strategy = JourneyStrategy(self, strategy_provider, enabled=vision_enabled)
        self.action_source = "idle"
        self._start_provider_health_check()

    def _tactical_usage_provider(self):
        provider = getattr(self.policy, "provider", None)
        return getattr(provider, "usage_provider", "jev")

    def _provider_label(self):
        return self._tactical_usage_provider().title()

    def _start_provider_health_check(self):
        health = getattr(getattr(self.policy, "provider", None), "health", None)
        if not callable(health):
            self.provider_health = "ready"
            return
        if self.provider_health != "ready":
            self.provider_health = "checking"
        self.provider_health_error = ""
        self.provider_health_future = self.executor.submit(health)

    def _set_provider_event(self, message):
        self.provider_events.append(str(message)[:180])

    def pop_provider_event(self):
        return self.provider_events.popleft() if self.provider_events else None

    def _poll_provider_health(self):
        if (self.provider_health_future is None and self.provider_health == 'unavailable'
                and self.playback.requested and monotonic() >= self.playback.retry_at):
            self.playback.status = 'recovering'
            self._start_provider_health_check()
        if (self.provider_health_future is None and self.provider_health == "ready"
                and monotonic() - self.provider_health_checked_at >= 10):
            self.provider_health_checked_at = monotonic()
            self._start_provider_health_check()
        if self.provider_health_future is None or not self.provider_health_future.done():
            return
        future, self.provider_health_future = self.provider_health_future, None
        self.provider_health_checked_at = monotonic()
        try:
            result = future.result()
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise RuntimeError("sidecar health response was not ok")
        except Exception as exc:
            self.provider_health = "unavailable"
            self.provider_health_error = f"{type(exc).__name__}: {exc}"
            if self.playback.status != 'blocked':
                self.playback.waiting(self.provider_health_error)
            self._set_provider_event(f"{self._provider_label()} unavailable: {self.provider_health_error}")
            # Verified opening goals and single-option dialogue do not require
            # the tactical sidecar. A later multi-option request will still fail
            # closed through the normal provider error path.
            return
        self.provider_health = "ready"
        self.provider_health_error = ""
        if self.playback.requested and self.playback.status in {'recovering', 'waiting for provider'}:
            self.paused = False
            self.pause_reason = ''
            self.strategy.invalidate()
            self.playback.ready()

    @staticmethod
    def _location(state):
        return (f"{state.map_group:02X}:{state.map_number:02X}",
                (state.x, state.y))

    def _observe_move(self, state):
        if state.x is None or state.y is None or not state.map_group:
            return
        key, position = self._location(state)
        self.memory.visited(key, position)
        self.movement_history.observe(key, position)
        if self.last:
            old_key, origin, action = self.last
            if action in _STEPS and old_key == key:
                if position != origin:
                    delta = (position[0] - origin[0], position[1] - origin[1])
                    observed = next((d for d, step in _STEPS.items() if step == delta), None)
                    self.last_move_direction = observed
                    self.memory.move_result(key, origin, action, position)
                    self._set_provider_event(
                        f"Moved {observed or 'across tiles'} to {position[0]},{position[1]}"
                    )
                    self.stalls = 0
                    self.replans_at.pop((key, origin), None)
                    self.last = None
                    # Replan immediately at the new tile. If the next route
                    # step has the same heading, the native D-pad hold remains
                    # down and walking continues without a release/repress gap.
                    self.cooldown = 0
                elif self.cooldown == 0:
                    self.held_action = None
                    self.memory.move_result(key, origin, action, position)
                    self._set_provider_event(
                        f"Blocked {action} at {position[0]},{position[1]}"
                    )
                    self.stalls += 1
                    self.last = None
                    if self.stalls >= 8:
                        place = (key, position)
                        cycles = self.replans_at.get(place, 0) + 1
                        self.replans_at[place] = cycles
                        self.stalls = 0
                        self.decision_future = None
                        self.screen_note = None
                        self.cooldown = 12
                        self._set_provider_event(
                            f"Replanning from map at {position[0]},{position[1]}"
                        )
                        return True
            elif old_key != key:
                self.held_action = None
                self.memory.remember("exit", f"{old_key} {origin} -> {key} {position}")
                self.last = None

    def _finish_encounter(self, state):
        if not self.encounter or state.in_battle or not self.encounter["started"]:
            return
        encounter = self.encounter
        self.encounter = None
        if encounter["species_id"] in state.pokedex_caught_ids:
            self.memory.remember("capture", encounter["species"], encounter["map"])
            return
        key = (encounter["map"], encounter["species_id"])
        self.attempts[key] = self.attempts.get(key, 0) + 1
        self.pause("Static encounter ended without a capture; inspect before continuing")

    def pause(self, reason):
        if 'unavailable' in reason and reason.startswith(('Laya', 'Jev')):
            self.provider_health = 'unavailable'
            self.playback.waiting(reason)
        else:
            self.playback.blocked(reason)
        self.strategy.invalidate()
        self.paused = True
        self.pause_reason = reason
        self.held_action = None

    def resume(self):
        self.dialogue.reset()
        self.playback.request(True)
        self.strategy.invalidate()
        self.strategy.observations.pending = None
        self.strategy.failures = 0
        self.strategy.excluded.clear()
        self.strategy.rechecked_positions.clear()
        self.paused = False
        self.pause_reason = ""
        self.stalls = 0
        self.cooldown = 0
        self.unknown_frames = 0
        if self.decision_future is not None:
            self.decision_future.cancel()
        self.decision_future = None
        self.decision_key = None
        self.title_bootstrap_done = False
        self.held_action = None
        self.interaction_positions.clear()
        self.interaction_map_key = None
        if self.provider_health == "unavailable":
            self._start_provider_health_check()

    def _screen(self, state, frame):
        if self.vision is None or not self.strategy.use_luna:
            return None
        key = (state.map_group, state.map_number, state.x, state.y,
               state.battle.kind, getattr(state.battle.opponent, "hp", None))
        if self.vision_future:
            if not self.vision_future.done():
                return None
            try:
                note = self.vision_future.result()
            except Exception as exc:
                self.strategy.provider_failed(f"Luna screen reader: {type(exc).__name__}")
                note = {"mode": "unknown", "screen_text": [],
                        "uncertainty": type(exc).__name__}
            if note:
                self.usage.record("luna", **(note.get("usage") or {}))
            if self.vision_key == key and note:
                expected = "battle" if state.in_battle else "overworld"
                if state.in_battle and note["mode"] != expected:
                    note = None
                self.screen_note = note
                if note and note["mode"] == "dialogue":
                    self.memory.remember("clue", " ".join(note["screen_text"]),
                                         f"{state.map_group:02X}:{state.map_number:02X}")
                if note:
                    visible = " ".join(note.get("screen_text") or []).strip()
                    self._set_provider_event(
                        f"Luna read {note['mode']}: {visible or '(no text)'}"
                    )
            self.vision_future = None
        if self.paused:
            return None
        if self.screen_note and self.vision_key == key:
            return self.screen_note
        if frame is None:
            self._set_provider_event("Screen unavailable; advancing")
            return {"mode": "unknown", "screen_text": [],
                    "uncertainty": "no frame"}
        self.vision_key = key
        self.screen_note = None
        model_input = getattr(self.vision, "model_input", None)
        if callable(model_input):
            self.latest_model_input = {"provider": "Luna", **model_input(frame)}
            self._set_provider_event("Luna input · screen + image")
        self.vision_future = self.executor.submit(self.vision.describe, frame.copy())
        return None

    def _service_route(self, state, target, goal, *, arrival=None):
        """Walk to a service entrance using the same collision-aware route as story goals."""
        if state.x is None or state.y is None or target is None:
            return None
        position = (state.x, state.y)
        self.navigation_target = ((state.map_group, state.map_number), target)
        self.opening_goal = goal
        if position == target:
            # A warp at the map edge can require another step in its entrance
            # direction. A at the doorway leaves the player there forever.
            return arrival
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        action = _route(self.memory.map(key), position, target,
                        state.map_width, state.map_height,
                        avoid=self.interaction_positions | {
                            item_cell(e) for e in (self.map_state.snapshot.entities
                                                  if self.map_state.snapshot else ())},
                        terrain=self.terrain)
        if action:
            self.opening_goal = goal
            self.last = (key, position, action)
            self.held_action = action
            self.cooldown = _MOVE_HOLD_FRAMES
        return action

    def _recovery_action(self, state, *, overworld, prompt_visible=False):
        """Return a deterministic heal route, or None when no safe route is known."""
        if state.in_battle or not getattr(state, "party", ()):
            return None
        town_key = (state.map_group, state.map_number)
        check_in = (center_target(state) is not None and
                    getattr(state, "last_spawn_map", town_key) != town_key)
        if self.recovery is None and (needs_healing(state) or check_in):
            self.recovery = {"started": True, "attempts": 0}
            self._set_provider_event("Visiting the local Pokémon Center")
        if self.recovery is None:
            return None
        if is_center(state):
            from .gold97_services import fully_recovered
            if fully_recovered(state):
                self.recovery["exit"] = True
            if self.recovery.get("exit"):
                if not overworld:
                    return "a" if prompt_visible else None
                return self._service_route(state, (5, 7),
                                           "Leave the Pokémon Center", arrival="down")
            target = nurse_target(state)
            if not overworld:
                return "a" if prompt_visible else None
            if (state.x, state.y) == target:
                self._set_provider_event("Healing the party at the Pokémon Center")
                if not self.recovery.get("faced_nurse"):
                    self.recovery["faced_nurse"] = True
                    # Arrival coordinates can update before the walking animation
                    # finishes. Hold the facing direction before tapping A across
                    # the counter; a one-frame turn can be ignored by the ROM.
                    self.cooldown = _MOVE_HOLD_FRAMES
                    return "up"
                self.recovery["attempts"] += 1
                if self.recovery["attempts"] > 8:
                    self.pause("Pokémon Center nurse did not restore HP")
                    return None
                return "a"
            return self._service_route(state, target, "Heal at the Pokémon Center")
        if self.recovery.get("exit"):
            self.recovery = None
            self._set_provider_event("Pokémon Center visit complete")
            return None
        if not overworld:
            # A menu may already be open when the heal threshold is crossed.
            # Close it before sending walking directions toward the Center.
            return "b" if prompt_visible else None
        entrance = center_target(state)
        if entrance is None:
            retreat = center_retreat_target(state)
            if retreat is None:
                return None
            target, arrival = retreat
            return self._service_route(state, target,
                                       "Retreat to the Pokémon Center",
                                       arrival=arrival)
        action = self._service_route(state, entrance[0],
                                     "Return to the Pokémon Center", arrival="up")
        if action:
            self._set_provider_event("Returning to the Pokémon Center")
        return action

    def _shopping_action(self, state, *, overworld):
        """Buy Poké Balls only when the visible Mart screen confirms each step."""
        if self.recovery is not None or state.in_battle:
            return None
        if self.shopping is None:
            if not should_buy_balls(state):
                return None
            target = mart_target(state)
            if target is None:
                return None
            shop_key = ((state.map_group, state.map_number), state.money,
                        state.poke_ball_count)
            if shop_key in self.shopping_skip:
                return None
            self.shopping = {"target": target[0], "town": shop_key,
                             "last_balls": state.poke_ball_count,
                             "selected_ball": False, "last_ui": None,
                             "repeats": 0, "talks": 0}
            self._set_provider_event("Heading to the Mart for Poké Balls")
        plan = self.shopping
        if not is_mart(state):
            if plan.get("exit"):
                self.shopping = None
                return None
            return self._service_route(state, plan["target"], "Buy Poké Balls",
                                       arrival="up")
        if plan.get("exit"):
            if not overworld:
                return "b"
            return self._service_route(state, (4, 7), "Leave the Mart",
                                       arrival="down")
        balls = getattr(state, "poke_ball_count", 0)
        if balls > plan["last_balls"]:
            plan["last_balls"] = balls
            plan["selected_ball"] = False
            plan["last_ui"] = None
            plan["repeats"] = 0
            self._set_provider_event(f"Bought Poké Balls; now carrying {balls}")
        if not should_buy_balls(state):
            plan["exit"] = True
            return "b" if not overworld else self._service_route(
                state, (4, 7), "Leave the Mart", arrival="down")
        if not overworld:
            step = mart_menu_step(plan, state)
            if step is None:
                if (getattr(state, "screen_cursor", None) is None and
                        plan.get("transitions", 0) < 3):
                    # The indoor warp and Mart text can take several frames to
                    # finish drawing. Wait for a readable menu, without ever
                    # confirming an unidentified item or quantity prompt.
                    plan["transitions"] = plan.get("transitions", 0) + 1
                    return "wait"
                plan["exit"] = True
                self.shopping_skip.add((plan["town"][0], state.money, balls))
                self._set_provider_event("Mart screen unclear; leaving without using an item")
                return "b"
            action, phase = step
            plan["transitions"] = 0
            ui = (phase, getattr(state, "screen_cursor", None),
                  tuple(getattr(state, "screen_lines", ()) or ()))
            plan["repeats"] = plan["repeats"] + 1 if ui == plan["last_ui"] else 0
            plan["last_ui"] = ui
            if plan["repeats"] >= 3:
                plan["exit"] = True
                self.shopping_skip.add((plan["town"][0], state.money, balls))
                self._set_provider_event("Mart menu did not advance; leaving")
                return "b"
            return action
        if state.x is None or state.y is None:
            return None
        # The counter tile (2, 3) is blocked. Talk across it from (3, 3).
        clerk_tile = (3, 3)
        if (state.x, state.y) == clerk_tile:
            if not plan.get("faced_clerk"):
                plan["faced_clerk"] = True
                self.cooldown = _MOVE_HOLD_FRAMES
                return "left"
            plan["talks"] += 1
            if plan["talks"] > 3:
                plan["exit"] = True
                self.shopping_skip.add((plan["town"][0], state.money, balls))
                return self._service_route(state, (4, 7), "Leave the Mart",
                                           arrival="down")
            return "a"
        return self._service_route(state, clerk_tile, "Buy Poké Balls")

    @staticmethod
    def _escape_action(state):
        visible_menu = getattr(state, "battle_menu_kind", None)
        if visible_menu == "moves":
            return "b"
        if visible_menu == "text":
            lines = tuple(getattr(state, "screen_lines", ()) or ())
            if any("CANCEL" in line or "USE" in line for line in lines):
                return "b"
            return "a"
        cursor = getattr(state, "battle_menu_cursor", None)
        if cursor is None or cursor == (2, 2):
            return "a"
        if cursor[0] != 2:
            return "right"
        return "down"

    def _capture_action(self, state):
        """Use the battle PACK on a new hack-exclusive species, never on old ones."""
        foe = state.battle.opponent
        if not novel_capture(state, foe):
            self.capture = None
            return None
        # A weak party gets out of a wild encounter first.  Capturing is a
        # useful detour only when the active team can safely continue.
        if needs_healing(state):
            self.capture = None
            return None
        balls = getattr(state, "poke_ball_count", None)
        if balls is None or balls <= 0:
            self._set_provider_event("No Poké Balls; escaping the encounter")
            self.capture = {"species_id": foe.species_id, "phase": "escape",
                            "attempts": 0, "balls": 0, "steps": 0}
            return self._escape_action(state)
        if self.capture is None or self.capture.get("species_id") != foe.species_id:
            self.capture = {"species_id": foe.species_id, "phase": "menu",
                            "attempts": 0, "balls": balls, "steps": 0}
        plan = self.capture
        if balls < plan["balls"]:
            plan["attempts"] += plan["balls"] - balls
            plan["balls"] = balls
            plan["steps"] = 0
        if plan["attempts"] >= _MAX_CAPTURE_ATTEMPTS or plan["steps"] >= 12:
            plan["phase"] = "escape"
        if plan["phase"] == "escape":
            self._set_provider_event("Capture attempt ended; leaving the encounter")
            return self._escape_action(state)
        plan["steps"] += 1
        visible_menu = getattr(state, "battle_menu_kind", None)
        cursor = getattr(state, "battle_menu_cursor", None)
        if visible_menu == "moves":
            return "b"
        if visible_menu == "command" or visible_menu is None:
            # The ROM orders FIGHT/PKMN on the first row and PACK/RUN below.
            if cursor == (1, 2):
                plan["phase"] = "bag"
                return "a"
            if cursor is None:
                return "a"
            if cursor[0] == 2:
                return "left"
            return "down" if cursor[1] == 1 else "a"
        lines = tuple(getattr(state, "screen_lines", ()) or ())
        ball_row = next((row for row, line in enumerate(lines)
                         if "POK" in line.upper() and "BALL" in line.upper()), None)
        if ball_row is not None and any("USE" in line for line in lines):
            self._set_provider_event(f"Using a Poké Ball on {foe.species}")
            plan["phase"] = "throw"
            return "a"
        if ball_row is not None:
            screen_cursor = getattr(state, "screen_cursor", None)
            if screen_cursor and screen_cursor[1] != ball_row:
                return "down" if screen_cursor[1] < ball_row else "up"
            plan["phase"] = "select_ball"
            return "a"
        if any("CANCEL" in line for line in lines):
            # The bag initially opens in ITEMS, with POTION highlighted. Switch
            # pockets; never confirm an unidentified item as a Poké Ball.
            return "right"
        return "a"

    def _options(self, state, entities, overworld=True):
        if state.in_battle:
            foe = state.battle.opponent
            if foe is None:
                return {}
            return {"a": "confirm highlighted battle command", "b": "back or cancel",
                    "up": "move battle cursor up", "down": "move battle cursor down",
                    "left": "move battle cursor left", "right": "move battle cursor right"}
        if not overworld:
            text = ' '.join(getattr(state, 'screen_lines', ())).upper()
            if any(word in text for word in ('RELEASE', 'DEPOSIT', 'WITHDRAW', 'CHANGE BOX', 'STATS')):
                return {'b': 'leave an unowned roster menu'}
            if getattr(state, 'screen_cursor', None) is not None:
                return {'b': 'cancel an unidentified menu'}
            return {"a": "advance current dialogue"}
        if state.x is None or state.y is None or not state.map_group:
            return {}
        key, position = self._location(state)
        blocked = self.memory.map(key)["blocked"]
        options = {}
        walkable = {}
        for direction, (dx, dy) in _STEPS.items():
            target = (position[0] + dx, position[1] + dy)
            if (0 <= target[0] < state.map_width and
                    0 <= target[1] < state.map_height and
                    (self.terrain is None or self.terrain.allows(target, direction))):
                walkable[direction] = f"walk {direction} toward {target}"
                if [list(position), direction] not in blocked:
                    options[direction] = walkable[direction]
        visited = {tuple(point) for point in self.memory.map(key)["visited"]}
        unexplored = {
            direction: description for direction, description in options.items()
            if (position[0] + _STEPS[direction][0],
                position[1] + _STEPS[direction][1]) not in visited
        }
        if unexplored:
            options = unexplored
        exit_target = _KNOWN_EXITS.get((state.map_group, state.map_number))
        if exit_target and options:
            improving = {
                direction: description for direction, description in options.items()
                if abs(position[0] + _STEPS[direction][0] - exit_target[0])
                + abs(position[1] + _STEPS[direction][1] - exit_target[1])
                < abs(position[0] - exit_target[0]) + abs(position[1] - exit_target[1])
            }
            if improving:
                options = improving
        if self.last_move_direction and len(options) > 1:
            options.pop(_REVERSE[self.last_move_direction], None)
        if self.interaction_positions:
            options = {
                direction: description for direction, description in options.items()
                if (position[0] + _STEPS[direction][0],
                    position[1] + _STEPS[direction][1]) not in self.interaction_positions
            }
        if not options:
            # Blocked-edge memory can be stale after a transition or an input
            # timing miss. Retry a terrain-permitted step before inventing an
            # interaction with a nearby NPC or an empty doorway.
            options = {
                direction: description for direction, description in walkable.items()
                if (position[0] + _STEPS[direction][0],
                    position[1] + _STEPS[direction][1]) not in self.interaction_positions
            } or walkable
        return options

    def _item_detour(self, state, entities, *, overworld):
        """Give a visible item a first-class goal before story navigation."""
        if state.in_battle or not overworld:
            return None
        item_entities = tuple(entity for entity in entities if is_item_entity(entity))
        if not item_entities:
            return None
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        position = (state.x, state.y)
        item_positions = {item_cell(entity) for entity in item_entities}
        item_positions.discard(None)
        if position in self.interaction_positions:
            item_positions = {point for point in item_positions if point != position}
        action = item_action(self.memory, state, item_entities,
                             terrain=self.terrain, avoid=self.interaction_positions,
                             attempted=self.attempted_items)
        if action is None:
            return None
        target = min((point for point in item_positions if (key, point) not in self.attempted_items),
                     key=lambda point: abs(point[0] - position[0]) +
                     abs(point[1] - position[1]), default=None)
        if target is None:
            return None
        self.opening_goal = "Collect the nearby item before continuing"
        if action == "a":
            self.attempted_items.add((key, target))
            self.interaction_positions.add(position)
            self._set_provider_event("Collecting nearby item before continuing")
        else:
            self._set_provider_event("Heading to a nearby item before continuing")
        self.last = (key, position, action)
        self.held_action = action if action in _STEPS else None
        self.cooldown = (_MOVE_HOLD_FRAMES if action in _STEPS
                         else _MENU_COOLDOWN_FRAMES)
        return action

    def _battle_reset(self):
        self.wild_battle_committed = False
        self.battle_strategy.reset()
        self.battle_executor.reset()
        self.battle_phase = None
        self.battle_target = None
        self.battle_cursor_index = 0
        self.battle_pp_before = None
        self.battle_foe_hp_before = None
        self.battle_switch_target = None
        self.battle_switch_phase = None
        self.battle_switch_text = None

    def _trainer_battle_action(self, state):
        return self.battle_executor.step(self, state)

    def observe(self, state, entities=(), overworld=True, terrain=None, prompt_visible=None):
        """Also called during manual play and provider outages; never presses keys."""
        self.map_state.update(state, terrain, ready=terrain is not None,
                              overworld=overworld, entities=entities,
                              destination=self.navigation_target, connections=self.strategy.data['connections'])
        snapshot = self.map_state.snapshot
        self.terrain = snapshot.terrain if snapshot and overworld else terrain
        self.route.observe(state)
        self.strategy.observe(state, entities, overworld, prompt_visible)
        self.rewards.observe(state, self.route)
        self.rewards.observe_exploration(state, overworld=overworld)
        self.training.observe(state, self.route)

    def manual_pause(self):
        if self.party_reorder.phase:
            self.party_reorder.phase = 'close'
        if self.roster_service.transfer.phase:
            self.roster_service.transfer.phase = 'close'
        self.roster_service.target = None
        self.playback.request(False)
        self.strategy.invalidate()
        self.held_action = None
        self.paused = False
        self.pause_reason = ''

    def step(self, state, *, frame=None, entities=(), overworld=True,
             terrain=None, prompt_visible=None):
        self.last_decision = None
        if overworld or state.in_battle:
            self.dialogue.reset()
        self.observe(state, entities, overworld, terrain, prompt_visible)
        action = self._step(state, frame=frame, entities=entities, overworld=overworld,
                            terrain=terrain, prompt_visible=prompt_visible)
        if self.playback.requested and not self.paused and self.provider_health == 'ready':
            self.playback.ready()
        if self.paused:
            action = None
            self.held_action = None
        self.action_source = (
            self._provider_label() if action and self.last_decision and self.last_decision.request_made else
            "deterministic execution" if action else
            "paused" if self.paused else
            "awaiting Luna" if self.strategy.future else
            f"awaiting {self._provider_label()}" if self.decision_future else "idle")
        return action

    def _step(self, state, *, frame=None, entities=(), overworld=True,
              terrain=None, prompt_visible=None):
        """Return one button or None. Call once per emulated frame."""
        map_key = (state.map_group, state.map_number)
        if map_key != self.interaction_map_key:
            self.interaction_positions.clear()
            self.last_move_direction = None
            self.interaction_map_key = map_key
        snapshot = self.map_state.snapshot
        self.terrain = snapshot.terrain if snapshot and overworld else None
        self.route.observe(state)
        learned = proposed_move(state)
        if learned:
            self.learning_move = learned
        elif overworld and not state.in_battle:
            self.learning_move = None
        if self.route.to_dict() != self.memory.world.get("route"):
            self.memory.world["route"] = self.route.to_dict()
            self.memory.save()
        self._poll_provider_health()
        if self.paused and self.playback.status == 'blocked':
            return None
        if (not state.in_battle and self._tactical_usage_provider() == "laya"
                and self.provider_health != "ready"):
            self.last = None
            self.held_action = None
            if self.provider_health == "unavailable":
                self.pause(f"Laya unavailable: {self.provider_health_error}. Retry to reconnect.")
            return None
        if state.in_battle or not overworld:
            self.last = None
            self.held_action = None
            self.stalls = 0
            if not state.in_battle:
                self._battle_reset()
        elif self._observe_move(state):
            return None
        if not state.in_battle and self.wild_battle_committed:
            self._battle_reset()
        self.unknown_frames = 0 if overworld or state.in_battle else self.unknown_frames + 1
        if state.in_battle and state.battle.opponent:
            self.last_battle = (state.battle.kind, state.battle.opponent.species)
        elif self.last_battle:
            self.memory.remember("battle_end", "Encounter ended: " +
                                 " ".join(self.last_battle),
                                 f"{state.map_group:02X}:{state.map_number:02X}")
            if self.last_battle[0] == "trainer" and state.x is not None and state.y is not None:
                key, position = self._location(state)
                self.memory.clear_blocked_at(key, position)
            self.last_battle = None
        self._finish_encounter(state)
        if self.capture and not state.in_battle:
            species_id = self.capture["species_id"]
            if species_id in getattr(state, "pokedex_caught_ids", ()):
                self.memory.remember("capture", f"species {species_id}",
                                     f"{state.map_group:02X}:{state.map_number:02X}")
            self.capture = None
        if self.encounter and not self.encounter["started"] and not state.in_battle:
            self.pending_frames -= 1
            if self.pending_frames <= 0:
                self.encounter = None
        if self.cooldown:
            self.cooldown -= 1
            return None
        if self.paused:
            return None
        self.action_source = "deterministic execution"
        # A fresh cartridge starts on the title menu before any party/map state is
        # available. Select the highlighted NEW GAME entry once so a local provider
        # can take over the subsequent naming, dialogue, and movement decisions.
        if (not self.title_bootstrap_done and not overworld and not state.in_battle
                and not state.party and map_key == (0, 0)):
            self.title_bootstrap_done = True
            self.held_action = "a"
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return "a"
        prompt = (_visible_prompt(state) if prompt_visible is None
                  else prompt_visible)
        if (not overworld and not state.in_battle and
                (self.unknown_frames < 8 or not prompt)):
            return None
        learning = learning_menu_step(state, self.learning_move)
        if learning is not None:
            action, detail = learning
            if action is None:
                self.pause(detail)
                return None
            self.last_decision = None
            self.held_action = None
            self._set_provider_event(detail)
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return action
        key, position = self._location(state)
        self.navigation_target = None
        if getattr(state, 'storage_verified', False):
            owned, roster_action = self.roster_service.step(state, overworld)
            if owned:
                self.held_action = roster_action if roster_action in _STEPS and overworld else None
                self.cooldown = _MOVE_HOLD_FRAMES if self.held_action else _MENU_COOLDOWN_FRAMES
                return roster_action
        recovery_action = self._recovery_action(
            state, overworld=overworld, prompt_visible=prompt)
        if recovery_action:
            self.last_decision = None
            self.held_action = recovery_action if recovery_action in _STEPS else None
            if recovery_action not in _STEPS:
                self.cooldown = _MENU_COOLDOWN_FRAMES
            return recovery_action
        opening = self.opening.choose(state, self.memory, overworld=overworld,
                                      terrain=self.terrain)
        # The opening planner historically emitted a fixed A for the scripted
        # rival battle. Keep its goal metadata, but let the battle planner own
        # the input sequence so it can avoid exhausted move slots.
        if (opening is not None and state.in_battle
                and state.battle.kind == "trainer" and opening[1] == "a"):
            self.opening_goal = opening[0]
            opening = None
        if opening is not None:
            goal, action = opening
            if goal != self.opening_goal:
                self.opening_goal = goal
                self._set_provider_event(f"Goal: {goal}")
            self.last_decision = None
            self.last = (key, position, action)
            self.held_action = action if action in _STEPS else None
            if action == "wait":
                self.wait_streak += 1
                if self.wait_streak >= _WAIT_LIMIT:
                    action = "a"
                    self.wait_streak = 0
                    self._set_provider_event("Advancing a stalled scripted scene")
                else:
                    self.cooldown = _MENU_COOLDOWN_FRAMES
                    return None
            else:
                self.wait_streak = 0
            self.cooldown = (_MOVE_HOLD_FRAMES if action in _STEPS
                             else _MENU_COOLDOWN_FRAMES)
            return None if action == "wait" else action
        if self.party_reorder.phase:
            action = self.party_reorder.step(state, overworld)
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return action
        service_action = self._shopping_action(state, overworld=overworld)
        if service_action:
            self.last_decision = None
            if service_action == "wait":
                self.held_action = None
                self.cooldown = 12
                return None
            self.held_action = service_action if service_action in _STEPS else None
            if service_action not in _STEPS:
                self.cooldown = _MENU_COOLDOWN_FRAMES
            return service_action
        if state.in_battle and self.encounter and self.encounter["species_id"] is None:
            foe = state.battle.opponent
            if state.battle.kind == "trainer":
                self.encounter = None
            elif foe:
                self.encounter["started"] = True
                self.encounter["species_id"] = foe.species_id
                self.encounter["species"] = foe.species
        foe = state.battle.opponent
        if state.in_battle and state.battle.kind == "wild":
            text = " ".join(" ".join(getattr(state, "screen_lines", ()) or ()).upper().split())
            active = getattr(state.battle, "active", None)
            forced = (getattr(state, "battle_menu_kind", None) in
                      {"forced_prompt", "party", "party_action"}
                      or (active is not None and active.hp <= 0))
            failed_escape = any(message in text for message in
                                ("CAN'T ESCAPE", "CANNOT ESCAPE", "CAN T ESCAPE"))
            self.wild_battle_committed |= forced or failed_escape
            if self.wild_battle_committed:
                self.capture = None
                action = self._trainer_battle_action(state)
                self.last_decision = None
                self.held_action = None
                self.cooldown = _MENU_COOLDOWN_FRAMES
                return action
        if state.in_battle:
            self.battle_strategy.static_capture = bool(self.encounter and self.encounter.get('started'))
            action = self._trainer_battle_action(state)
            self.last_decision = None
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return None if action == 'wait' else action
        strategy_active = (overworld and not state.in_battle and
                           self.route.now is not None and self.route.now >= 3 and
                           self.terrain is not None)
        training_required = self.training.required(state) if state.party else False
        if (overworld and state.party and getattr(state, 'mechanics_verified', False)
                and (not strategy_active or training_required)):
            lead = self.training.lead(state)
            if self.party_reorder.start(state, lead):
                self.held_action = None
                self.cooldown = _MENU_COOLDOWN_FRAMES
                return self.party_reorder.step(state, True)
            training = self.training.direction(state, self.terrain)
            if training:
                self.last = (key, position, training)
                self.held_action = training
                self.cooldown = _MOVE_HOLD_FRAMES
                return training
        if strategy_active:
            options = self.strategy.options(state, self.terrain)
            if not options:
                self.held_action = None
                return None
            if self.strategy.target:
                self.navigation_target = (map_key, tuple(self.strategy.target["cell"]))
        else:
            item_action_result = self._item_detour(state, entities, overworld=overworld)
            if item_action_result:
                self.last_decision = None
                return item_action_result
            navigation = journey_step(state, self.memory, self.route,
                                      overworld=overworld,
                                      avoid=self.interaction_positions,
                                      terrain=self.terrain)
            if navigation:
                goal, action = navigation
                if goal != self.opening_goal:
                    self.opening_goal = goal
                    self._set_provider_event(f"Goal: {goal}")
                key, position = self._location(state)
                self.last = (key, position, action)
                self.held_action = action
                self.cooldown = _MOVE_HOLD_FRAMES
                return action
            options = self._options(state, entities, overworld)
        if not options and overworld and not state.in_battle:
            map_key = (state.map_group, state.map_number, state.x, state.y,
                       state.battle.kind, getattr(state.battle.opponent, "hp", None))
            map_note = self.screen_note if self.vision_key == map_key else None
            if self.vision is not None and self.stalls >= 2:
                map_note = self._screen(state, frame)
            options = probe_options(state, self.memory, map_note)
        if not options:
            self.no_options_frames += 1
            if (overworld and not state.in_battle and self.no_options_frames >= 60):
                self.no_options_frames = 0
                self._set_provider_event("No direction confirmed yet; checking the map")
            return None
        self.no_options_frames = 0
        # Laya is the tactical provider for movement as well as menus and battles.
        # The frontier route is retained for legacy/non-Laya providers, where it
        # remains a deterministic safety path rather than a hidden substitute.
        if (not strategy_active and overworld and not state.in_battle and self.stalls == 0
                and self._tactical_usage_provider() != "laya"):
            route = frontier_step(self.memory.map(key), position,
                                  state.map_width, state.map_height)
            if route in options:
                self.last = (key, position, route)
                self.held_action = route
                self.cooldown = _MOVE_HOLD_FRAMES
                return route
        note = self.screen_note if self.vision_key == (
            state.map_group, state.map_number, state.x, state.y,
            state.battle.kind, getattr(state.battle.opponent, "hp", None)) else None
        # Laya uses Luna only for uncertain overworld navigation; ordinary text
        # and battles continue from cartridge state without extra model calls.
        use_vision = (
            ((self.stalls >= 3 or self.movement_history.looping) and overworld) or
            (self._tactical_usage_provider() != "laya" and
             (state.in_battle or not overworld))
        )
        if self.vision is not None and self.strategy.enabled and use_vision:
            note = self._screen(state, frame)
            if note is None and (state.in_battle or not overworld):
                # Text and battle screens can advance while a transcription is
                # pending. A stalled overworld route still needs a direction.
                self.held_action = None
                self.cooldown = _MENU_COOLDOWN_FRAMES
                return "a"
            if not state.in_battle and not overworld and note is not None and note["mode"] not in {"menu", "dialogue"}:
                self._set_provider_event("Screen mode unclear; advancing")
                self.held_action = None
                self.cooldown = _MENU_COOLDOWN_FRAMES
                return "a"
        if not strategy_active and overworld and not state.in_battle and self.movement_history.looping:
            area = self.memory.map(key)
            route = frontier_step(area, position, state.map_width, state.map_height,
                                  terrain=self.terrain, avoid=self.interaction_positions)
            if route:
                options = {route: "retrace the map toward unexplored ground"}
            elif note and note.get("mode") == "overworld":
                visual = {d: text for d, text in options.items()
                          if d in note.get("walkable_directions", ())}
                options = visual or options
            action = self.movement_history.choose(key, position, options)
            options = {action: options[action]}
        body = decision_state(state, self.memory, note, key, position)
        body["journey"] = self.strategy.context(state)
        body["strategy"] = self.strategy.data.get("plan")
        body["luna_enabled"] = self.strategy.enabled
        step = self.route.now
        if step is not None:
            body["goal"] = f"Complete Journey step {step}: {MAIN[step]}"
            body["journey_step"] = step
        from .game_loop import GenericBranch
        decision_key = (key, position, state.battle.kind,
                        getattr(state.battle.opponent, "hp", None),
                        tuple(options), str(note), self.route.now, self.strategy.generation)
        if self.decision_future is None:
            branch = GenericBranch(body["decision_kind"], body, options)
            self.decision_key = decision_key
            self.decision_future = self.executor.submit(self.policy.decide, branch)
            return None
        if not self.decision_future.done():
            return None
        if self.decision_key != decision_key:
            self.decision_future = None
            return None
        try:
            decision = self.decision_future.result()
        except Exception as exc:
            self.pause(f"{self._provider_label()} unavailable: {type(exc).__name__}")
            self._set_provider_event(f"{self._provider_label()} error: {type(exc).__name__}")
            return None
        finally:
            self.decision_future = None
        self.last_decision = decision
        if decision.request_made:
            if decision.model_input:
                self.latest_model_input = {
                    "provider": self._provider_label(),
                    **decision.model_input,
                }
                kind = body.get("decision_kind", "decision")
                self._set_provider_event(
                    f"{self._provider_label()} input · {kind} · "
                    f"{', '.join(options)}"
                )
            self.usage.record(
                self._tactical_usage_provider(),
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                total_tokens=decision.total_tokens,
                latency_ms=decision.latency_ms,
                actual_cost_usd=decision.actual_cost_usd,
            )
        if decision.option == "wait":
            # Waiting is not a gameplay objective. Older Laya sidecars can still
            # emit the retired token, so translate it to a legal forward input
            # instead of letting the agent idle forever or treating it as a fatal
            # policy error.
            action = next((name for name in
                           ("up", "down", "left", "right", "a", "b", "start")
                           if name in options), None)
            if action is None:
                action = next(iter(options), "a")
            self.wait_streak += 1
            self._set_provider_event(f"{self._provider_label()} wait replaced with {action}")
        elif decision.option not in options:
            self.pause(f"{self._provider_label()} returned an invalid choice")
            self._set_provider_event(f"{self._provider_label()} returned an invalid choice")
            return None
        else:
            action = decision.option
        if (action == "a" and not overworld and not state.in_battle
                and getattr(state, "screen_cursor", None) is None):
            action = self.dialogue.advance(state)
            if action is None:
                self.pause("Dialogue did not change after confirmation and cancel attempts. Inspect the screen, then Retry.")
                return None
        if decision.fell_back:
            self.pause(f"{self._provider_label()} unavailable: {decision.reason}. Retry to reconnect.")
            self.provider_health = "unavailable"
            self.provider_health_error = decision.reason
            self._set_provider_event(self.pause_reason)
            return None
        elif decision.option != "wait":
            source = self._provider_label() if decision.request_made else "Executor (only legal action)"
            self._set_provider_event(f"{source} chose {action}")
        self.action_source = self._provider_label()
        if strategy_active:
            self.strategy.chosen(action)
        if action != "wait":
            self.wait_streak = 0
        if action == "a":
            self.interaction_positions.add(position)
        adjacent_sprite = any(
            abs(entity.pixel_x - state.x * 16) +
            abs(entity.pixel_y - state.y * 16) == 16 for entity in entities
        ) if state.x is not None and state.y is not None else False
        if action == "a" and adjacent_sprite and overworld and self.save_encounter:
            path = self.save_encounter()
            if path:
                self.memory.checkpoint(path)
                self.encounter = {"checkpoint": path, "species_id": None,
                                  "species": "", "map": key, "started": False}
                self.pending_frames = 90
        self.last = (key, position, action)
        self.held_action = None if action == "wait" else action
        self.cooldown = (_MOVE_HOLD_FRAMES if action in _STEPS
                         else _MENU_COOLDOWN_FRAMES)
        if state.in_battle or not overworld:
            self.screen_note = None
            self.vision_key = None
        return None if action == "wait" else action

    def close(self):
        if self.strategy.future:
            self.strategy.future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        provider = getattr(self.policy, "provider", None)
        close_provider = getattr(provider, "close", None)
        if callable(close_provider):
            close_provider()
        self.memory.close()

    def usage_snapshot(self):
        return self.usage.snapshot()
