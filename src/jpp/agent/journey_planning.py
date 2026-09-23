"""Candidate selection and planner dispatch, separate from journey lifecycle."""
from time import monotonic
from copy import deepcopy
from .journey_targets import candidates, paths, target_options
from .journey_knowledge import record
from .navigation_policy import collectible, preferred_targets


class JourneyPlanning:
    def reconsider_interaction(self, state, terrain, durable):
        if (not self.target or getattr(state, 'player_moving', False)
                or collectible(self.target) or self.target.get('retreat_reason')):
            return
        available = candidates(state, self.owner.memory, terrain,
                               excluded=self.excluded | durable,
                               reward_weights=self.owner.rewards.weights)
        current_reward = next((target.get('journey_reward', 0) for target in available
                               if target['id'] == self.target['id']), 0)
        direct = next((target for target in available if target['kind'] == 'talk'
                       and target.get('category') != 'obstacle'
                       and (collectible(target) or self.target.get('category') == 'obstacle'
                            or target.get('goal_interaction')
                            or target['cell'] == [state.x, state.y])
                       and (collectible(target)
                            or target.get('journey_reward', 0) > current_reward)), None)
        pickups = preferred_targets([t for t in available if collectible(t)])
        if pickups and (not direct or pickups[0].get('journey_reward', 0)
                        >= direct.get('journey_reward', 0)):
            direct = pickups[0]
        if direct and collectible(direct):
            if self.target['kind'] in {'exit', 'explore'}:
                self.data['resume_target'] = {'goal': self.owner.route.now,
                                            'target': deepcopy(self.target)}
            self.invalidate()
            self.target, self.status = direct, 'ready'
            self.data['selection_source'] = 'Collectible detour'
            record(self.owner.memory, 'collectible_detour', direct['id'])
            return
        if direct and (self.required or self.shared_control):
            self.invalidate()
            return
        if direct:
            self.invalidate()
            self.target, self.status = direct, 'ready'
            self.data['plan'] = {'target': direct['id'], 'explanation': direct['label'],
                                 'completion': direct['completion'], 'evidence': [direct['id']]}

    def plan_next(self, state, terrain, durable):
        # Map collision data is briefly unavailable after a cartridge map
        # transition while Gold97CollisionCache samples the new map. Planning
        # during that window can omit collision-gated routes (including Surf)
        # and ask Qwen to choose from an incomplete list of exits.
        if getattr(state, 'mechanics_verified', False) and terrain is None:
            if self.status != 'waiting_for_terrain':
                self.owner._set_provider_event(
                    'Waiting for current map collision data before planning'
                )
            self.status = 'waiting_for_terrain'
            return {}
        if self.required and not self.use_luna:
            return {}
        if self.required and self.future and not self.future.done():
            return {}
        if monotonic() < self.recovery_retry_at:
            return {}
        recovering = False
        available = candidates(
            state, self.owner.memory, terrain, excluded=self.excluded | durable,
            reward_weights=self.owner.rewards.weights,
        )
        # A timed-out step or a moving sprite can leave all exits remembered
        # as blocked. Recheck the current tile once, using cartridge collision
        # data and observed sprites as the authority for the retry.
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        position = (state.x, state.y)
        from .navigation_memory import evidence_stamp
        retry_key = (key, position, evidence_stamp(self.owner.memory, self.owner.route.now, key))
        if (not available and terrain is not None
                and retry_key not in self.rechecked_positions
                and len(paths(state, self.owner.memory, terrain)) == 1
                and any(edge[0] == list(position)
                        for edge in self.owner.memory.map(key)["blocked"])):
            self.rechecked_positions.add(retry_key)
            self.owner.memory.clear_blocked_at(key, position)
            available = candidates(
                state, self.owner.memory, terrain, excluded=self.excluded | durable,
                reward_weights=self.owner.rewards.weights,
            )
        if not available:
            available = self.recovery_candidates(state, terrain)
            recovering = bool(available)
        if not available:
            # When every reachable lead was excluded by remembered failures,
            # retry those approaches once at this exact map position and
            # evidence revision. New movement or story evidence permits a
            # later retry; an unchanged dead end cannot spin on the same door.
            failures = self.owner.memory.experience.failures(self.owner.route.now)
            retry_key = (key, position, evidence_stamp(
                self.owner.memory, self.owner.route.now, key))
            if failures and retry_key not in self.empty_retry_keys:
                self.empty_retry_keys.add(retry_key)
                self.owner.memory.experience.retry(self.owner.route.now)
                self.excluded.clear()
                self.data.pop('blocker', None)
                available = candidates(
                    state, self.owner.memory, terrain,
                    excluded=self.excluded,
                    reward_weights=self.owner.rewards.weights,
                )
                recovering = bool(available)
                if available:
                    self.owner._set_provider_event(
                        'Rechecking reachable routes after exhausting remembered approaches'
                    )
        if not available:
            # Keep observing and retry transient obstacles without spinning
            # model requests or requiring a manual resume.
            self.recovery_retry_at = monotonic() + 2
            from .object_memory import obstruction_summary
            self.status = "blocked"
            failures = [item for item in self.owner.memory.experience.failures(self.owner.route.now)
                        if item.get('map') == key]
            self.data['blocker'] = (f"{failures[-1]['label']}: {failures[-1]['reason']}. "
                                    "Needs new evidence or Retry." if failures else
                                    obstruction_summary(self.data, key))
            self.owner._set_provider_event(self.data['blocker'])
            return {}
        local = [t for t in available if not t.get('landing_return')]
        if local:
            available = local
        resume = self.data.get('resume_target')
        if resume and not any(collectible(t) or t.get('retreat_reason') for t in available):
            self.data.pop('resume_target', None)
            target = next((t for t in available if t['id'] == resume['target']['id']), None)
            if target and resume['goal'] == self.owner.route.now and target['map'] == key:
                self.target, self.status = target, 'ready'
                self.data['selection_source'] = 'Route continuation'
                record(self.owner.memory, 'route_resumed', target['id'])
                return self.options(state, terrain)
        available = self.prioritize_forward_routes(available)
        available = preferred_targets(available)
        useful = [target for target in available if target.get('journey_reward', 0) > 0]
        if useful:
            available = useful
        if all(t.get("recent_return") for t in available):
            # Historical failures must not leave the just-used door as the
            # sole perpetual choice. Recheck an older local lead first.
            alternatives = self.recovery_candidates(state, terrain)
            forward = [t for t in alternatives
                       if t.get("destination_key") != self.arrived_from]
            if forward:
                available = self.prioritize_forward_routes(forward)
                recovering = True
        forward = [t for t in available if not t.get("recent_return")]
        if forward:
            available = forward
        self.payload = self.context(state)
        self.payload["candidates"] = available
        from .navigation_memory import navigation_memory
        self.payload['navigation_memory'] = navigation_memory(self, state, available)
        self.payload = deepcopy(self.payload)
        milestone_reward = self.owner.rewards.weights["milestone"]
        top = available[0]
        if len(available) == 1:
            # Commit the sole reachable subgoal. Returning its first movement
            # action without a target makes the frontier recompute every tile;
            # partial visibility can then alternate between adjacent camera
            # viewpoints forever instead of finishing the route approach.
            self.target = top
            self.local_targets = {
                action: top for action in target_options(top, state, self.owner.memory, terrain)
                if action != 'a'
            }
            self.status = 'ready'
            self.data['selection_source'] = 'Route continuation'
            self.data['plan'] = {'target': top['id'], 'explanation': top['label'],
                                 'completion': top['completion'], 'evidence': [top['id']]}
            self.data['plan_review'] = 'Only one reachable subgoal; committed until observed'
            record(self.owner.memory, 'journey_priority', top['label'],
                   reward=top.get('journey_reward', 0))
            return self.options(state, terrain)
        top_choice = (("exit", top.get("destination_key"))
                      if top.get("kind") == "exit" and top.get("destination_key")
                      else ("target", top["id"]))
        runner_up = next((target.get("journey_reward", 0) for target in available[1:]
                          if (("exit", target.get("destination_key"))
                              if target.get("kind") == "exit" and target.get("destination_key")
                              else ("target", target["id"])) != top_choice), -1)
        top_priority = (
            top.get('investigation_priority') or top.get('prerequisite') or top.get('goal_route')
            or top.get('reobserve_interaction')
            or (top.get("route_frontier") and not recovering)
            or ((top.get('goal_destination') or top.get('goal_interaction'))
                and top.get("journey_reward", 0) >= milestone_reward)
        )
        if (not self.required and not self.shared_control and top_priority
                and runner_up < top["journey_reward"]):
            self.data["selection_source"] = "Route continuation"
            self.target = top
            self.status = "ready"
            self.data["plan"] = {"target": self.target["id"],
                                 "explanation": self.target["label"],
                                 "completion": self.target["completion"],
                                 "evidence": [self.target["id"]]}
            record(self.owner.memory, "journey_priority", self.target["label"],
                   reward=self.target["journey_reward"])
            return self.options(state, terrain)
        if self.use_luna:
            for target in available:
                if target.get("source"):
                    record(self.owner.memory, "guide", target["label"], source=target["source"])
            self.status = "planning"
            self.plan_identity = self.request_identity(state)
            self.plan_started_at = monotonic()
            model_input = getattr(self.provider, "model_input", None)
            if callable(model_input):
                try:
                    self.owner.latest_model_input = {'provider': self.label, **model_input(self.payload)}
                except Exception as exc:
                    self.provider_failed(f'{self.label} context unavailable: {str(exc)[:120]}')
                    return self.local_options(state, terrain, available) if self.shared_control else {}
                self.owner._set_provider_event(
                    f"{self.label} input · strategy · {len(available)} candidates"
                )
            self.submitted_input = self.owner.latest_model_input
            visual = getattr(self.provider, "plan_visual", None)
            frame = getattr(self.owner, "planning_frame", None)
            self.plan_has_image = callable(visual) and frame is not None
            if self.plan_has_image:
                frame = frame.copy()
                overview = None
                snapshot = getattr(self.owner.map_state, 'snapshot', None)
                from .navigation_overview import render_navigation_overview
                if snapshot is not None and not self.owner.map_state.status:
                    overview = render_navigation_overview(
                        snapshot.terrain, state, self.owner.memory,
                        (self.payload.get('travel') or {}).get('next_map'))
                context = self.owner.latest_model_input.setdefault('context', {})
                context['map_overview'] = {
                    'attached': overview is not None,
                    'map': f'{state.map_group:02X}:{state.map_number:02X}',
                    'size': list(overview.size) if overview is not None else None,
                }
                self.owner.live.vision_started(frame, self.owner.latest_model_input)
                self.owner._set_provider_event(f"{self.label} planning with game image")
                pages = getattr(self.owner, "dialogue_captures", [])
                self.plan_dialogue_key = (pages[-1]['map'], pages[-1]['signature']) if pages else None
                fresh = self.plan_dialogue_key != getattr(self, 'accepted_dialogue_key', None)
                recent_frames = [p['frame'] for p in pages[-1:] if fresh and p['frame'] is not None]
                self.future = self.owner.executor.submit(visual, self.payload, frame,
                                                         recent_frames, overview)
            else:
                self.future = self.owner.executor.submit(self.provider.plan, self.payload)
            self.plan_id = self.owner.memory.experience.record('planner_request', payload=self.payload,
                                                 model=getattr(self.provider, 'model', None),
                                                 context=(self.submitted_input or {}).get('context'))
            return self.local_options(state, terrain, available) if self.shared_control else {}
        return self.local_options(state, terrain, available)

    def prioritize_forward_routes(self, available):
        """Make a just-used doorway less valuable while alternatives exist."""
        source = getattr(self, "arrived_from", None)
        if not source:
            return available
        milestone = self.owner.rewards.weights["milestone"]
        prioritized = []
        for target in available:
            if (((target.get('prerequisite') or target.get('goal_route')) and not target.get('recent_return'))
                    or target.get("kind") != "exit"
                    or target.get("destination_key") != source):
                prioritized.append(target)
                continue
            target = {**target, "recent_return": True,
                      "journey_reward": max(0, target.get("journey_reward", 0) - milestone)}
            reason = target.get("reward_reason", "")
            target["reward_reason"] = (reason + "; " if reason else "") + "immediate return to the map just left"
            prioritized.append(target)
        return sorted(prioritized, key=lambda target: -target.get("journey_reward", 0))


    def recovery_candidates(self, state, terrain):
        """Recover reachable leads without reopening unchanged failures."""
        available = candidates(state, self.owner.memory, terrain,
                               reward_weights=self.owner.rewards.weights)
        from .navigation_memory import allowed_targets
        return allowed_targets(self.owner.memory, self.owner.route.now, available)
