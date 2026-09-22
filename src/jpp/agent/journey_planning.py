"""Candidate selection and planner dispatch, separate from journey lifecycle."""
from time import monotonic
from .journey_targets import candidates, paths, target_options
from .journey_knowledge import record
from .experience import target_key


class JourneyPlanning:
    def reconsider_obstacle(self, state, terrain, durable):
        if not self.target or self.target.get('category') != 'obstacle':
            return
        available = candidates(state, self.owner.memory, terrain,
                               excluded=self.excluded | durable,
                               reward_weights=self.owner.rewards.weights)
        current_reward = next((target.get('journey_reward', 0) for target in available
                               if target['id'] == self.target['id']), 0)
        direct = next((target for target in available if target['kind'] == 'talk'
                       and target.get('category') != 'obstacle'
                       and target.get('journey_reward', 0) > current_reward), None)
        if direct:
            self.invalidate()
            self.target, self.status = direct, 'ready'
            self.data['plan'] = {'target': direct['id'], 'explanation': direct['label'],
                                 'completion': direct['completion'], 'evidence': [direct['id']]}

    def plan_next(self, state, terrain, durable):
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
        retry_key = (key, position)
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
            # Keep observing and retry transient obstacles without spinning
            # model requests or requiring a manual resume.
            self.recovery_retry_at = monotonic() + 2
            self.rechecked_positions.discard(retry_key)
            from .object_memory import obstruction_summary
            self.status = "blocked"
            self.owner._set_provider_event(obstruction_summary(self.data, key))
            return {}
        local = [t for t in available if not t.get('landing_return')]
        if local:
            available = local
        investigations = [t for t in available if t.get('investigation_priority')]
        if investigations:
            available = investigations
        interactions = [t for t in available if t.get('goal_interaction')]
        if interactions:
            available = interactions
        available = self.prioritize_forward_routes(available)
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
        milestone_reward = self.owner.rewards.weights["milestone"]
        top = available[0]
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
        if (top_priority
                and runner_up < top["journey_reward"]):
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
            self.plan_started_at = monotonic()
            model_input = getattr(self.provider, "model_input", None)
            if callable(model_input):
                self.owner.latest_model_input = {
                    "provider": "Luna",
                    **model_input(self.payload),
                }
                self.owner._set_provider_event(
                    f"Luna input · strategy · {len(available)} candidates"
                )
            self.future = self.owner.executor.submit(self.provider.plan, self.payload)
            self.owner.memory.experience.record('planner_request', payload=self.payload,
                                                 model=getattr(self.provider, 'model', None))
            return {}
        # Laya receives all reachable tasks; it selects the task and its next legal
        # control together. No Luna-produced plan remains active in this mode.
        options = {}
        self.local_targets = {}
        for target in available:
            for action, label in target_options(target, state, self.owner.memory, terrain).items():
                if action == "a":
                    continue  # First commit the task and establish facing.
                options.setdefault(action, label)
                self.local_targets.setdefault(action, target)
        return options

    def prioritize_forward_routes(self, available):
        """Make a just-used doorway less valuable while alternatives exist."""
        source = getattr(self, "arrived_from", None)
        if not source:
            return available
        milestone = self.owner.rewards.weights["milestone"]
        prioritized = []
        for target in available:
            if (target.get('prerequisite') or target.get('goal_route') or target.get("kind") != "exit"
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
        """Reconsider observed leads after alternatives are exhausted."""
        available = candidates(state, self.owner.memory, terrain,
                               reward_weights=self.owner.rewards.weights)
        failures = self.owner.memory.experience.failures(self.owner.route.now)
        attempted = {item['target_key']: item['timestamp'] for item in failures}
        if available:
            # Retry the oldest failed approach first; retain Journey ranking
            # among equally fresh leads and never erase durable experience.
            oldest = min(attempted.get(target_key(t), 0) for t in available)
            available = [t for t in available
                         if attempted.get(target_key(t), 0) == oldest]
            record(self.owner.memory, "route_recheck", available[0]["label"])
            return available
        return []
