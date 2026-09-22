"""Observe journey transitions without confusing loading frames with arrivals."""

from .journey_knowledge import JourneyKnowledge, record


class JourneyObservation:
    def observe(self, state, entities, overworld, prompt_visible=None):
        self.poll_retired()
        if id(self.owner.memory.world) != self.world_id:
            self.field_action.phase = None
            self.owner.hm_teaching.phase = None
            self.world_id = id(self.owner.memory.world)
            self.observations = JourneyKnowledge(self.owner.memory)
            self.invalidate()
            self.goal = None
        current = self.owner.route.now
        from .journey_hms import capability_key
        hm_key = capability_key(state)
        from .hm_preparation import observe_encounter
        from ..field_moves import HM_NAMES, normalize
        observe_encounter(self.owner.memory, state)
        self.owner.memory.world['field_capabilities'] = [
            list(getattr(state, 'owned_hms', ())), list(getattr(state, 'badge_ids', ())),
            sorted({normalize(move) for mon in getattr(state, 'party', ())
                    for move in getattr(mon, 'moves', ()) if normalize(move) in
                    {normalize(name) for name in HM_NAMES}}),
            sorted({move for mon in getattr(state, 'party', ())
                    for move in getattr(getattr(mon, 'species_data', None), 'field_moves', ())})]
        previous_hms = getattr(self, 'hm_key', None)
        self.hm_key = hm_key
        self.owner.memory.world['navigation_capabilities'] = [
            repr(hm_key), bool(getattr(state, 'route_103_slowpoke_cleared', False))]
        if previous_hms is not None and previous_hms != hm_key:
            self.excluded.clear()
            self.maps_since_evidence.clear()
            self.invalidate()
        key = (state.map_group, state.map_number)
        key_name = f"{state.map_group:02X}:{state.map_number:02X}"
        pending = self.observations.pending
        previous_map = self.observations.last_map
        previous_position = self.observations.last_position
        same_map_warp = (
            overworld and not state.in_battle and previous_position is not None
            and self.observations.last_map == key_name
            and abs(state.x - previous_position[0]) + abs(state.y - previous_position[1]) > 1
            and any(tuple(exit[:2]) == tuple(previous_position)
                    for exit in self.observations.last_exits)
        )
        if overworld and previous_map and previous_position and (previous_map != key_name or same_map_warp):
            from .exploration_cycles import record_transition
            target = self.target or self.last_transition_target
            cell = (target['cell'] if target and target['kind'] == 'exit'
                    and target['map'] == previous_map else previous_position)
            record_transition(self.owner.memory, previous_map, cell, key_name)
        if same_map_warp:
            record(self.owner.memory, "subgoal_completed",
                   self.target["id"] if self.target else "Observed same-map stair transition")
            self.failures = 0
            self.owner.movement_history.points.clear()
            self.invalidate()
        changed = self.observations.observe(state, entities, overworld=overworld,
                                            milestone=current, prompt_visible=prompt_visible)
        if pending and not self.observations.pending:
            self.owner.memory.clear_transient_blocks(key_name)
        if overworld and previous_map and previous_map != key_name:
            # RAM map IDs change during fades, before the first coherent map
            # frame. Use the last observed map, not that transient ID change.
            self.arrived_from = previous_map
            self.owner.memory.world['navigation_arrival'] = {
                'map': key_name, 'from': previous_map, 'cell': [state.x, state.y], 'goal': current}
            self.owner.memory.save()
            self.maps_since_evidence.append(key)
            self.maps_since_evidence = self.maps_since_evidence[-12:]
        if (overworld and not state.in_battle and current is not None
                and state.x is not None and state.y is not None):
            route_maps = self.data["route_maps"].setdefault(str(current), [])
            if key_name not in route_maps:
                route_maps.append(key_name)
                route_maps[:] = route_maps[-48:]
                self.owner.memory.save()
        if current != self.goal or key != self.map_key:
            if self.goal is not None and current != self.goal:
                record(self.owner.memory, "milestone_change", str(current))
            if current != self.goal:
                self.arrived_from = None
                if current is not None:
                    self.owner.memory.experience.retire_guides(current)
                self.maps_since_evidence.clear()
            elif self.map_key is not None and key != self.map_key:
                if overworld and previous_map is None:
                    self.arrived_from = f"{self.map_key[0]:02X}:{self.map_key[1]:02X}"
                self.last_transition_target = self.target
            self.goal, self.map_key = current, key
            self.excluded.clear()
            self.invalidate()
        elif changed:
            # Seeing another sprite or another text page does not cancel a
            # committed route. Replan after the conversation actually closes.
            if ((pending and not self.observations.pending) or
                    (not self.target and not self.future and not self.observations.pending)):
                self.failures = 0
                self.excluded.clear()
                self.owner.movement_history.points.clear()
                self.maps_since_evidence.clear()
                self.invalidate()
        if self.maps_since_evidence.count(key) >= 3:
            self.maps_since_evidence.clear()
            self.failed("Repeated map cycle without new dialogue or discoveries")
        if overworld and not state.in_battle and self.target:
            from .interaction_refresh import refresh_interaction
            refresh_interaction(self.target, self.data['npcs'])
        if self.target and self.target["kind"] == "explore":
            if [state.x, state.y] == self.target["cell"]:
                if self.target.get('reobserve_interaction'):
                    npc = self.data['npcs'].get(self.target['id'], {})
                    if not npc.get('visible'):
                        # Coordinates can arrive before the sprites/camera do.
                        # Only a settled overworld view can disprove a lead.
                        if not overworld or state.in_battle or getattr(state, 'player_moving', False):
                            self.target['reobserve_ticks'] = 0
                            return
                        self.target['reobserve_ticks'] = self.target.get('reobserve_ticks', 0) + 1
                        if self.target['reobserve_ticks'] < 24:
                            return
                        self.failed('Last-seen person was not found at the observed location')
                        return
                from .navigation_trace import record_target
                from .exploration_cycles import evidence
                record_target(self.owner.memory, self.target)
                start = self.target.get('evidence_at_start')
                discovered = start is not None and start != repr(evidence(self.owner.memory))
                record(self.owner.memory, "subgoal_completed" if discovered else "exploration_reached",
                       self.target["id"])
                # Reaching another viewpoint is not fresh evidence by itself.
                # Keep the loop detector across empty waypoints, so a circle
                # cannot reset its history by changing targets along the way.
                if discovered:
                    self.failures = 0
                    self.owner.movement_history.points.clear()
                self.invalidate(preserve_pending=True)
