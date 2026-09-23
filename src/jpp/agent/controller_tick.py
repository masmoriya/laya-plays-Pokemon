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
        prompt = (_visible_prompt(state) if prompt_visible is None
                  else prompt_visible)
        local_dialogue = (not state.in_battle and not overworld and prompt
                          and getattr(state, 'screen_cursor', None) is None)
        if map_key != self.interaction_map_key:
            self.interaction_positions.clear()
            self.last_move_direction = None
            self.interaction_map_key = map_key
        snapshot = self.map_state.snapshot
        self.terrain = snapshot.terrain if snapshot and overworld else None
        if not state.in_battle and self.live.current.get('kind') == 'battle':
            self.live.decide(kind='observation', source='Game state',
                             why='Battle ended; reading the current screen',
                             action='Read dialogue' if not overworld else 'Resume journey')
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
                and self.provider_health != "ready" and not local_dialogue):
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
        if overworld and not state.in_battle and getattr(state, 'player_moving', False):
            from .route_execution import committed_heading
            if not committed_heading(self, state, self.held_action):
                self.held_action = None
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
            if state.x is not None and state.y is not None:
                key, position = self._location(state)
                self.memory.clear_transient_blocks(key)
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
        from .gold97_screen import pc_screen
        # Cancel incidental storage before healing or navigation confirms it.
        if pc_screen(state) and not state.in_battle and not self.roster_service.transfer.phase:
            page = tuple(getattr(state, "screen_lines", ()))
            previous, attempts = getattr(self, "pc_escape", (None, 0))
            attempts = attempts + 1 if page == previous else 1
            self.pc_escape = (page, attempts)
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            self._set_provider_event("Closing the PC to resume the journey")
            if attempts > 6:
                self.pause("PC screen did not change after cancel attempts. Inspect the screen, then Retry.")
                return None
            return "b"
        self.pc_escape = (None, 0)
        prompt = (_visible_prompt(state) if prompt_visible is None
                  else prompt_visible)
        if (not overworld and not state.in_battle and
                (self.unknown_frames < 8 or not prompt)):
            return None
        field = self.strategy.field_action
        if field.phase:
            action = field.step(state, overworld)
            self.held_action = action if action in _STEPS and overworld else None
            self.cooldown = _MOVE_HOLD_FRAMES if self.held_action else _MENU_COOLDOWN_FRAMES
            if field.phase is None:
                surf = self.strategy.target
                tile = (self.terrain.tile((state.x, state.y))
                        if self.terrain is not None and state.x is not None and state.y is not None
                        else None)
                from ..gold97_collision import _WATER
                if (getattr(field, 'move', None) == 'SURF' and not field.error and surf
                        and surf.get('surf_activation') and tile in _WATER):
                    exit_cell = surf['target_cell']
                    self.strategy.target = {
                        **surf, 'id': f"geometry:{surf['map']}:{exit_cell[0]}:{exit_cell[1]}:{surf['direction']}",
                        'kind': 'exit', 'cell': list(exit_cell), 'surf_activation': False,
                        'direction': '', 'label': f"Cross to {surf['destination']}",
                        'completion': f"Observe arrival in {surf['destination']}",
                    }
                    self.strategy.status = 'ready'
                    self.memory.experience.record('surf_activated',
                        destination=surf.get('destination_key'), position=[state.x, state.y])
                    self.memory.save()
                else:
                    if getattr(field, 'move', None) == 'SURF' and not field.error:
                        field.error = 'Surf activation did not place the player on water'
                    if surf and surf.get('surf_activation'):
                        self.strategy.failed(field.error or 'Surf activation failed')
                    else:
                        self.strategy.invalidate()
                if field.error:
                    self._set_provider_event(field.error)
            return action
        from .field_actions import field_confirmation
        confirmation = field_confirmation(state) if not overworld and not state.in_battle else None
        if confirmation:
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            self._set_provider_event('Confirm the usable field move')
            return confirmation
        teaching = self.hm_teaching
        if (not teaching.phase and overworld and not state.in_battle
                and not self.recovery and not self.party_reorder.phase
                and not self.roster_service.transfer.phase and not self.strategy.observations.pending):
            if teaching.start(state, self.route.now):
                self.strategy.invalidate()
                self._set_provider_event(f"Teach {teaching.plan['move']} to the compatible party Pokemon")
        if teaching.phase:
            action = teaching.step(state, overworld)
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            if teaching.phase is None:
                self.strategy.invalidate()
                if teaching.error:
                    self.pause(teaching.error)
                else:
                    self._set_provider_event(f"Verified {teaching.plan['move']} in the party")
            return action
        learning = learning_menu_step(state, self.learning_move)
        if learning is not None:
            action, detail = learning
            if action is None:
                self.pause(detail)
                return None
            self.last_decision = None
            self.held_action = None
            self._set_provider_event(detail)
            if action == 'wait':
                self.cooldown = 6
                return None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return action
        if (not overworld and not state.in_battle and prompt
                and getattr(state, 'screen_cursor', None) is None):
            # Cursorless visible text is always forward dialogue. Handle it
            # before healing, shopping, opening, and Journey planners can
            # reinterpret the retained map coordinates as a movement task.
            self.last_decision = None
            self.held_action = None
            self.last = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            self._set_provider_event('Advance visible dialogue')
            from .dialogue_capture import before_advance
            before_advance(self, state, frame)
            return self.dialogue.advance(state, frame)
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
        # Wild turns, including failed escapes, return to the same planner.
        # Menu execution handles forced replacements without committing to a fight.
        if state.in_battle:
            self.battle_strategy.static_capture = bool(self.encounter and self.encounter.get('started'))
            action = self._trainer_battle_action(state)
            self.last_decision = None
            self.held_action = None
            self.cooldown = _MENU_COOLDOWN_FRAMES
            return None if action == 'wait' else action
        return CONTINUE
