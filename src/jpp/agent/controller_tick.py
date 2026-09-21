"""Gold97 controller tick responsibilities."""

from .gold97_learning import learning_menu_step, proposed_move
from .controller_constants import CONTINUE, _MENU_COOLDOWN_FRAMES, _MOVE_HOLD_FRAMES, _STEPS, _WAIT_LIMIT, _visible_prompt

class TickExecution:
    def _step(self, state, **context):
        if not self._prepare_step(state, **context):
            return None
        action = self._scripted_step(state, **context)
        if action is not CONTINUE:
            return action
        return self._navigate_step(state, **context)

    def _prepare_step(self, state, *, frame=None, entities=(), overworld=True, terrain=None, prompt_visible=None):
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
            return False
        if (not state.in_battle and self._tactical_usage_provider() == "laya"
                and self.provider_health != "ready"):
            self.last = None
            self.held_action = None
            if self.provider_health == "unavailable":
                self.pause(f"Laya unavailable: {self.provider_health_error}. Retry to reconnect.")
            return False
        if state.in_battle or not overworld:
            self.last = None
            self.held_action = None
            self.stalls = 0
            if not state.in_battle:
                self._battle_reset()
        elif self._observe_move(state):
            return False
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
            return False
        if self.paused:
            return False
        return True

    def _scripted_step(self, state, *, frame=None, entities=(), overworld=True, terrain=None, prompt_visible=None):
        map_key = (state.map_group, state.map_number)
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
        return CONTINUE
