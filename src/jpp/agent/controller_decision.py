"""Gold97 controller decision responsibilities."""

from .gold97_map_probe import probe_options
from .gold97_navigation import frontier_step
from .gold97_journey_nav import journey_step
from .controller_constants import _MENU_COOLDOWN_FRAMES, _MOVE_HOLD_FRAMES
from .controller_choice import DecisionChoice


class DecisionExecution(DecisionChoice):
    def _navigate_step(self, state, *, frame=None, entities=(), overworld=True, terrain=None, prompt_visible=None):
        map_key = (state.map_group, state.map_number)
        key, position = self._location(state)
        strategy_active = (overworld and not state.in_battle and
                           self.route.now is not None and
                           self.terrain is not None)
        training_required = self.training.required(state) if state.party else False
        if (overworld and state.party and not training_required
                and getattr(state, 'mechanics_verified', False)):
            lead = self.training.travel_lead(state, self.terrain)
            if self.party_reorder.start(state, lead):
                self.held_action = None
                self.cooldown = _MENU_COOLDOWN_FRAMES
                return self.party_reorder.step(state, True)
        if (overworld and state.party and getattr(state, 'mechanics_verified', False)
                and training_required and self.terrain is not None
                and (state.area_name in self.training.data.get('opponents', {})
                     or self.terrain.tile((state.x, state.y)) in {0x10, 0x14, 0x18, 0x1C})):
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
        return self._decide_step(
            state, entities, overworld, options, note, key, position,
            strategy_active, frame=frame,
        )
