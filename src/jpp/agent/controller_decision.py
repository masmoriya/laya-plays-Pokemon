"""Gold97 controller decision responsibilities."""

from .gold97_map_probe import probe_options
from .gold97_navigation import frontier_step
from .gold97_journey_nav import journey_step
from .gold97_state import decision_state
from ..route_progress import MAIN
from .controller_constants import _MENU_COOLDOWN_FRAMES, _MOVE_HOLD_FRAMES, _STEPS

class DecisionExecution:
    def _navigate_step(self, state, *, frame=None, entities=(), overworld=True, terrain=None, prompt_visible=None):
        map_key = (state.map_group, state.map_number)
        key, position = self._location(state)
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
        return self._decide_step(state, entities, overworld, options, note, key, position, strategy_active)

    def _decide_step(self, state, entities, overworld, options, note, key, position, strategy_active):
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
