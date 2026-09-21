"""Candidate selection and planner dispatch, separate from journey lifecycle."""
from time import monotonic
from .journey_targets import candidates, paths, target_options
from .journey_knowledge import record
from .experience import target_key


class JourneyPlanning:
    def plan_next(self, state, terrain, durable):
        if monotonic() < self.recovery_retry_at:
            return {}
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
        if not available:
            # Keep observing and retry transient obstacles without spinning
            # model requests or requiring a manual resume.
            self.recovery_retry_at = monotonic() + 2
            self.rechecked_positions.discard(retry_key)
            self.status = "recovering"
            self.owner._set_provider_event("Rechecking reachable routes for the journey")
            return {}
        self.payload = self.context(state)
        self.payload["candidates"] = available
        milestone_reward = self.owner.rewards.weights["milestone"]
        runner_up = available[1].get("journey_reward", 0) if len(available) > 1 else -1
        if (available[0].get('goal_destination')
                and available[0].get("journey_reward", 0) >= milestone_reward
                and runner_up < available[0]["journey_reward"]):
            self.target = available[0]
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
        # Revisit reachable ground to refresh observations when all tiles are
        # known. Collision data and visible sprites still constrain BFS.
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        reachable = paths(state, self.owner.memory, terrain)
        cells = [cell for cell in reachable if cell != (state.x, state.y)]
        if not cells:
            return []
        def priority(cell):
            target = {"map": key, "kind": "explore", "cell": list(cell), "direction": ""}
            return (attempted.get(target_key(target), 0),
                    -abs(cell[0] - state.x) - abs(cell[1] - state.y))
        cell = min(cells, key=priority)
        return [{"id": f"explore:{key}:{cell}", "kind": "explore",
                 "cell": list(cell), "direction": "", "map": key,
                 "label": "Recheck the area for a route onward",
                 "completion": "Reach the target tile"}]
