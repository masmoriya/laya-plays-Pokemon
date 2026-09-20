"""Gold 97's Jev-led, text-first controller shared by live and headless play."""

from concurrent.futures import ThreadPoolExecutor

from .gold97_memory import Gold97Memory
from .gold97_navigation import frontier_step
from .gold97_state import decision_state
from .gold97_vision import LunaScreenReader
from .old_species import hack_exclusive
from .policy_adapter import ProviderPolicy
from .providers.jev_provider import JevProvider
from .usage import UsageTotals


_STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class Gold97Controller:
    def __init__(self, run_id, *, database="data/jev.sqlite", policy=None,
                 vision=None, save_encounter=None, restore_encounter=None):
        self.memory = Gold97Memory(run_id, database)
        self.policy = policy or ProviderPolicy(JevProvider())
        self.vision = vision or LunaScreenReader()
        self.save_encounter = save_encounter
        self.restore_encounter = restore_encounter
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.vision_future = None
        self.decision_future = None
        self.decision_key = None
        self.vision_key = None
        self.screen_note = None
        self.last = None
        self.cooldown = 0
        self.stalls = 0
        self.unknown_frames = 0
        self.paused = False
        self.pause_reason = ""
        self.encounter = None
        self.pending_frames = 0
        self.attempts = {}
        self.last_decision = None
        self.last_battle = None
        self.usage = UsageTotals()

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
                    self.memory.move_result(key, origin, action, position)
                    self.stalls = 0
                    self.last = None
                elif self.cooldown == 0:
                    self.memory.move_result(key, origin, action, position)
                    self.stalls += 1
                    self.last = None
            elif old_key != key:
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
        self.last = None
        self.screen_note = None
        self.vision_key = None
        self.decision_future = None
        self.cooldown = 20

    def pause(self, reason):
        self.paused = True
        self.pause_reason = reason

    def resume(self):
        self.paused = False
        self.pause_reason = ""
        self.stalls = 0

    def _screen(self, state, frame):
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
            if state.battle.kind == "wild" and not self.encounter and (
                    foe is None or not hack_exclusive(foe.species)):
                self.pause("Wild encounter is not verified hack-exclusive; take over to flee")
                return {}
            return {"a": "confirm highlighted battle command", "b": "back or cancel",
                    "up": "move battle cursor up", "down": "move battle cursor down",
                    "left": "move battle cursor left", "right": "move battle cursor right",
                    "wait": "wait for animation"}
        if not overworld:
            return {"a": "advance or confirm visible dialogue/menu",
                    "b": "cancel or back out", "up": "move menu cursor up",
                    "down": "move menu cursor down", "wait": "wait for animation"}
        if state.x is None or state.y is None or not state.map_group:
            return {}
        key, position = self._location(state)
        blocked = self.memory.map(key)["blocked"]
        options = {}
        for direction, (dx, dy) in _STEPS.items():
            target = (position[0] + dx, position[1] + dy)
            if (0 <= target[0] < state.map_width and
                    0 <= target[1] < state.map_height and
                    [list(position), direction] not in blocked):
                options[direction] = f"walk {direction} toward {target}"
        adjacent = [entity for entity in entities if
                    abs(entity.pixel_x - state.x * 16) +
                    abs(entity.pixel_y - state.y * 16) == 16]
        options["a"] = ("interact with a visible adjacent sprite" if adjacent
                        else "inspect the object directly in front, if any")
        options["wait"] = "wait for the current animation"
        return options

    def step(self, state, *, frame=None, entities=(), overworld=True):
        """Return one button or None. Call once per emulated frame."""
        self._observe_move(state)
        self.unknown_frames = 0 if overworld or state.in_battle else self.unknown_frames + 1
        if state.in_battle and state.battle.opponent:
            self.last_battle = (state.battle.kind, state.battle.opponent.species)
        elif self.last_battle:
            self.memory.remember("battle_end", "Encounter ended: " +
                                 " ".join(self.last_battle),
                                 f"{state.map_group:02X}:{state.map_number:02X}")
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
        if not overworld and not state.in_battle and self.unknown_frames < 8:
            return None
        key, position = self._location(state)
        if state.in_battle and self.encounter and self.encounter["species_id"] is None:
            foe = state.battle.opponent
            if state.battle.kind == "trainer":
                self.encounter = None
            elif foe:
                self.encounter["started"] = True
                self.encounter["species_id"] = foe.species_id
                self.encounter["species"] = foe.species
        options = self._options(state, entities, overworld)
        if not options:
            self._screen(state, frame)
            return None
        if overworld and not state.in_battle and self.stalls == 0:
            route = frontier_step(self.memory.map(key), position,
                                  state.map_width, state.map_height)
            if route in options:
                self.last = (key, position, route)
                self.cooldown = 20
                return route
        note = self.screen_note if self.vision_key == (
            state.map_group, state.map_number, state.x, state.y,
            state.battle.kind, getattr(state.battle.opponent, "hp", None)) else None
        if state.in_battle or not overworld or self.stalls >= 3:
            note = self._screen(state, frame)
            if note is None:
                return None
            if not state.in_battle and not overworld and note["mode"] not in {"menu", "dialogue"}:
                self.pause("Screen is not a verified menu or dialogue")
                return None
        body = decision_state(state, self.memory, note, key, position)
        from .game_loop import GenericBranch
        decision_key = (key, position, state.battle.kind,
                        getattr(state.battle.opponent, "hp", None),
                        tuple(options), str(note))
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
            self.pause(f"Jev unavailable: {type(exc).__name__}")
            return None
        finally:
            self.decision_future = None
        self.last_decision = decision
        if decision.request_made:
            self.usage.record(
                "jev",
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                total_tokens=decision.total_tokens,
                latency_ms=decision.latency_ms,
                actual_cost_usd=decision.actual_cost_usd,
            )
        if decision.fell_back or decision.option not in options:
            self.pause("Jev unavailable or returned an invalid choice")
            return None
        action = decision.option
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
        self.cooldown = 20 if action in _STEPS else 8
        if state.in_battle or not overworld:
            self.screen_note = None
            self.vision_key = None
        return None if action == "wait" else action

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.memory.close()

    def usage_snapshot(self):
        return self.usage.snapshot()
