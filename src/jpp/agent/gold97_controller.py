"""Gold 97's closed-set controller shared by live and headless play."""

from concurrent.futures import ThreadPoolExecutor

from .gold97_memory import Gold97Memory
from .gold97_navigation import frontier_step
from .gold97_opening import Gold97Opening
from .gold97_journey_nav import journey_step
from .gold97_state import decision_state
from .gold97_vision import LunaScreenReader
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


class Gold97Controller:
    def __init__(self, run_id, *, database="data/jev.sqlite", policy=None,
                 vision=None, vision_enabled=True, save_encounter=None,
                 restore_encounter=None, restore_stuck=None):
        self.memory = Gold97Memory(run_id, database)
        self.opening = Gold97Opening()
        self.route = RouteProgress.from_dict(self.memory.world.get("route"))
        self.opening_goal = None
        self.policy = policy or ProviderPolicy(JevProvider())
        self.vision = vision if vision is not None else (LunaScreenReader() if vision_enabled else None)
        self.save_encounter = save_encounter
        self.restore_encounter = restore_encounter
        self.restore_stuck = restore_stuck
        self.stuck_restores = 0
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.vision_future = None
        self.decision_future = None
        self.decision_key = None
        self.vision_key = None
        self.screen_note = None
        self.last = None
        self.cooldown = 0
        self.stalls = 0
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
        self.last_battle = None
        self.healing = None
        self.terrain = None
        self.usage = UsageTotals()
        self.held_action = None
        self.last_move_direction = None
        self.interaction_positions = set()
        self.provider_health_future = None
        self.provider_health = "unknown"
        self.provider_health_error = ""
        self.provider_event = None
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
        self.provider_health = "checking"
        self.provider_health_error = ""
        self.provider_health_future = self.executor.submit(health)

    def _set_provider_event(self, message):
        self.provider_event = str(message)[:180]

    def pop_provider_event(self):
        event, self.provider_event = self.provider_event, None
        return event

    def _poll_provider_health(self):
        if self.provider_health_future is None or not self.provider_health_future.done():
            return
        future, self.provider_health_future = self.provider_health_future, None
        try:
            result = future.result()
            if not isinstance(result, dict) or result.get("status") != "ok":
                raise RuntimeError("sidecar health response was not ok")
        except Exception as exc:
            self.provider_health = "unavailable"
            self.provider_health_error = f"{type(exc).__name__}: {exc}"
            self._set_provider_event(f"{self._provider_label()} unavailable: {self.provider_health_error}")
            # Verified opening goals and single-option dialogue do not require
            # the tactical sidecar. A later multi-option request will still fail
            # closed through the normal provider error path.
            return
        self.provider_health = "ready"
        self.provider_health_error = ""
        self._set_provider_event(f"{self._provider_label()} sidecar ready")

    @staticmethod
    def _location(state):
        return (f"{state.map_group:02X}:{state.map_number:02X}",
                (state.x, state.y))

    def _observe_move(self, state):
        if state.x is None or state.y is None or not state.map_group:
            return
        key, position = self._location(state)
        self.memory.visited(key, position)
        if self.last:
            old_key, origin, action = self.last
            if action in _STEPS and old_key == key:
                if position != origin:
                    self.held_action = None
                    self.last_move_direction = action
                    self.memory.move_result(key, origin, action, position)
                    self._set_provider_event(
                        f"Moved {action} to {position[0]},{position[1]}"
                    )
                    self.stalls = 0
                    self.replans_at.pop((key, origin), None)
                    self.last = None
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
                        bedroom = (state.map_group == 20 and state.map_number == 7
                                   and not getattr(state, "read_oaks_email", True))
                        if (self.restore_stuck and self.stuck_restores < 3
                                and (bedroom or cycles >= 3)):
                            try:
                                recovered = self.restore_stuck()
                            except OSError:
                                recovered = None
                            if recovered:
                                self.stuck_restores += 1
                                if not self.memory.restore(recovered):
                                    self.memory.reset()
                                self.route = RouteProgress.from_dict(
                                    self.memory.world.get("route"))
                                self.opening = Gold97Opening()
                                self.opening_goal = None
                                self.interaction_positions.clear()
                                self.screen_note = None
                                self.decision_future = None
                                self.held_action = None
                                self.cooldown = 24
                                self.stalls = 0
                                self.replans_at.clear()
                                self._set_provider_event("Movement stalled; restored a checkpoint")
                                return True
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
        if self.attempts[key] > 3 or not self.restore_encounter:
            self.pause("Static encounter lost; manual review needed")
            return
        self.restore_encounter(encounter["checkpoint"])
        self.memory.restore(encounter["checkpoint"])
        self.route = RouteProgress.from_dict(self.memory.world.get("route"))
        self.last = None
        self.held_action = None
        self.screen_note = None
        self.vision_key = None
        self.decision_future = None
        self.cooldown = 20

    def pause(self, reason):
        self.paused = True
        self.pause_reason = reason
        self.held_action = None

    def resume(self):
        self.paused = False
        self.pause_reason = ""
        self.stalls = 0
        self.title_bootstrap_done = False
        self.held_action = None
        if self.provider_health == "unavailable":
            self._start_provider_health_check()

    def _screen(self, state, frame):
        if self.vision is None:
            return None
        key = (state.map_group, state.map_number, state.x, state.y,
               state.battle.kind, getattr(state.battle.opponent, "hp", None))
        if self.vision_future:
            if not self.vision_future.done():
                return None
            try:
                note = self.vision_future.result()
            except Exception as exc:
                self.pause(f"Screen unclear and Luna unavailable: {type(exc).__name__}")
                note = None
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
            self.pause("Screen unclear and no frame available")
            return None
        self.vision_key = key
        self.screen_note = None
        self.vision_future = self.executor.submit(self.vision.describe, frame.copy())
        return None

    def _options(self, state, entities, overworld=True):
        if state.in_battle:
            foe = state.battle.opponent
            if foe is None:
                return {}
            return {"a": "confirm highlighted battle command", "b": "back or cancel",
                    "up": "move battle cursor up", "down": "move battle cursor down",
                    "left": "move battle cursor left", "right": "move battle cursor right",
                    "wait": "wait for animation"}
        if not overworld:
            # Gold 97's RAM adapter does not decode the text-box cursor yet. A/B
            # back-out guesses can leave a dialogue open forever, so make the safe
            # forward action the only autonomous menu choice until a menu decoder is
            # available. Battles retain their full closed set above.
            return {"a": "advance current dialogue or confirm the highlighted menu"}
        if state.x is None or state.y is None or not state.map_group:
            return {}
        key, position = self._location(state)
        blocked = self.memory.map(key)["blocked"]
        options = {}
        for direction, (dx, dy) in _STEPS.items():
            target = (position[0] + dx, position[1] + dy)
            if (0 <= target[0] < state.map_width and
                    0 <= target[1] < state.map_height and
                    (self.terrain is None or self.terrain.allows(target, direction)) and
                    [list(position), direction] not in blocked):
                options[direction] = f"walk {direction} toward {target}"
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
        adjacent = [entity for entity in entities if
                    abs(entity.pixel_x - state.x * 16) +
                    abs(entity.pixel_y - state.y * 16) == 16]
        # Pressing A in open overworld space is a no-op. Do not offer it as a
        # tempting model choice unless an interaction is visible or every
        # surrounding direction is blocked and an object may be in front.
        if adjacent:
            options["a"] = "interact with a visible adjacent sprite"
        elif not options:
            options["a"] = "inspect the object directly in front, if any"
        if position in self.interaction_positions:
            options.pop("a", None)
        if not options:
            options["wait"] = "wait for the current animation"
        return options

    def step(self, state, *, frame=None, entities=(), overworld=True,
             terrain=None):
        """Return one button or None. Call once per emulated frame."""
        self.terrain = (terrain if terrain is not None and
                        terrain.map_key == (state.map_group, state.map_number)
                        else None)
        before_route = self.route.to_dict()
        self.route.observe(state)
        if self.route.to_dict() != before_route:
            self.memory.world["route"] = self.route.to_dict()
            self.memory.save()
        self._poll_provider_health()
        if state.in_battle or not overworld:
            self.last = None
            self.held_action = None
            self.stalls = 0
        elif self._observe_move(state):
            return None
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
        if self.encounter and not self.encounter["started"] and not state.in_battle:
            self.pending_frames -= 1
            if self.pending_frames <= 0:
                self.encounter = None
        if self.cooldown:
            self.cooldown -= 1
            return None
        if self.paused:
            return None
        if self.provider_health == "checking":
            return None
        # A fresh cartridge starts on the title menu before any party/map state is
        # available. Select the highlighted NEW GAME entry once so a local provider
        # can take over the subsequent naming, dialogue, and movement decisions.
        if (not self.title_bootstrap_done and not overworld and not state.in_battle
                and not state.party):
            self.title_bootstrap_done = True
            self.held_action = "a"
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return "a"
        if not overworld and not state.in_battle and self.unknown_frames < 8:
            return None
        key, position = self._location(state)
        opening = self.opening.choose(state, self.memory, overworld=overworld,
                                      terrain=self.terrain)
        if opening is not None:
            goal, action = opening
            if goal != self.opening_goal:
                self.opening_goal = goal
                self._set_provider_event(f"Goal: {goal}")
            self.last_decision = None
            self.last = (key, position, action)
            self.held_action = action if action in _STEPS else None
            self.cooldown = (_MOVE_HOLD_FRAMES if action in _STEPS
                             else _MENU_COOLDOWN_FRAMES)
            return None if action == "wait" else action
        if state.in_battle and self.encounter and self.encounter["species_id"] is None:
            foe = state.battle.opponent
            if state.battle.kind == "trainer":
                self.encounter = None
            elif foe:
                self.encounter["started"] = True
                self.encounter["species_id"] = foe.species_id
                self.encounter["species"] = foe.species
        lead = state.party[0] if state.party else None
        if (self.healing is None and overworld and not state.in_battle and lead
                and getattr(state, "potion_count", 0) > 0
                and lead.hp > 0 and lead.hp * 2 < lead.max_hp):
            slot = getattr(state, "potion_slot", None)
            if slot is not None:
                self.healing = {"queue": ["start", "down", "down", "a"]
                                + ["down"] * slot + ["a", "a", "a"],
                                "initial_hp": lead.hp, "checks": 0}
                self._set_provider_event(f"Healing {lead.species} before continuing")
        if self.healing is not None:
            if self.healing["queue"]:
                action = self.healing["queue"].pop(0)
            elif lead and lead.hp > self.healing["initial_hp"]:
                if overworld:
                    self.healing = None
                    return None
                action = "b"
            else:
                self.healing["checks"] += 1
                if self.healing["checks"] > 4:
                    self.pause("Potion sequence did not restore HP; inspect the menu")
                    return None
                action = "a"
            self.last_decision = None
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return action
        foe = state.battle.opponent
        if (state.in_battle and state.battle.kind == "wild" and not self.encounter
                and foe is not None and not hack_exclusive(foe.species)):
            # Gold 97's 2x2 FIGHT/PKMN/PACK/RUN menu ignores B. A choice-only
            # model can otherwise press B forever, so navigate RUN from the
            # cartridge's live menu cursor and advance battle text with A.
            cursor = getattr(state, "battle_menu_cursor", None)
            if cursor is None or cursor == (2, 2):
                action = "a"
            elif cursor[0] != 2:
                action = "right"
            else:
                action = "down"
            self.last_decision = None
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return action
        if state.in_battle and state.battle.kind == "trainer":
            # The command menu starts on FIGHT and B is disabled. Confirming
            # advances text and selects the first move; unlike Laya's repeated
            # B, this has been exercised against the Route 101 cave trainer.
            action = "a"
            self.last_decision = None
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return action
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
        if not options:
            self.no_options_frames += 1
            if (overworld and not state.in_battle and self.no_options_frames >= 60):
                self.no_options_frames = 0
                self.cooldown = _MENU_COOLDOWN_FRAMES
                self._set_provider_event("No route available; checking nearby interaction")
                return "a"
            self._screen(state, frame)
            return None
        self.no_options_frames = 0
        # Laya is the tactical provider for movement as well as menus and battles.
        # The frontier route is retained for legacy/non-Laya providers, where it
        # remains a deterministic safety path rather than a hidden substitute.
        if (overworld and not state.in_battle and self.stalls == 0
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
        # Laya is intentionally local-only, so it can make the closed-set choice from
        # cartridge state/options without paying for screen transcription.
        if self.vision is not None and (state.in_battle or not overworld or self.stalls >= 3):
            note = self._screen(state, frame)
            if note is None:
                return None
            if not state.in_battle and not overworld and note["mode"] not in {"menu", "dialogue"}:
                self.pause("Screen is not a verified menu or dialogue")
                return None
        body = decision_state(state, self.memory, note, key, position)
        step = self.route.now
        if step is not None:
            body["goal"] = f"Complete Journey step {step}: {MAIN[step]}"
            body["journey_step"] = step
        if state.in_battle and state.battle.kind == "wild" and not self.encounter:
            foe = state.battle.opponent
            if foe is not None and not hack_exclusive(foe.species):
                body["battle_instruction"] = (
                    "This is not a verified hack-exclusive catch. Escape using RUN; "
                    "do not throw a ball."
                )
        from .game_loop import GenericBranch
        decision_key = (key, position, state.battle.kind,
                        getattr(state.battle.opponent, "hp", None),
                        tuple(options), str(note), self.route.now)
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
            self.usage.record(
                self._tactical_usage_provider(),
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                total_tokens=decision.total_tokens,
                latency_ms=decision.latency_ms,
                actual_cost_usd=decision.actual_cost_usd,
            )
        if decision.option not in options:
            self.pause(f"{self._provider_label()} returned an invalid choice")
            self._set_provider_event(f"{self._provider_label()} returned an invalid choice")
            return None
        if decision.fell_back:
            # Keep the closed-set safety fallback, but make it explicit in the live
            # feed. No other provider is substituted for the configured provider.
            self._set_provider_event(
                f"{self._provider_label()} fallback: {decision.reason}"
            )
            if self._tactical_usage_provider() != "laya":
                self.pause(f"{self._provider_label()} unavailable")
                return None
        else:
            self._set_provider_event(f"{self._provider_label()} chose {decision.option}")
        action = decision.option
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
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.memory.close()

    def usage_snapshot(self):
        return self.usage.snapshot()
