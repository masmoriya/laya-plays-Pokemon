"""Event-driven journey planning shared by live and headless controllers."""

from time import monotonic
from .journey_context import strategy_context, strategy_summary
from .journey_knowledge import JourneyKnowledge, knowledge, record
from .journey_strategy_provider import JourneyStrategyProvider, validate_plan
from .journey_targets import candidates, paths, target_options


class JourneyStrategy:
    def __init__(self, controller, provider=None, enabled=True):
        self.owner = controller
        self.default_enabled = enabled
        self.provider = provider or JourneyStrategyProvider()
        knowledge(controller.memory, enabled)
        self.observations = JourneyKnowledge(controller.memory)
        self.future = None
        self.generation = 0
        self.goal = None
        self.map_key = None
        self.target = None
        self.payload = None
        self.failures = 0
        self.excluded = set()
        self.loop_latched = False
        self.facing = None
        self.status = "idle"
        self.world_id = id(controller.memory.world)
        self.retired = []
        self.maps_since_evidence = []
        self.rechecked_positions = set()
        self.retry_at = 0
        self.provider_failures = 0
        self.plan_started_at = 0

    @property
    def data(self):
        return knowledge(self.owner.memory, self.default_enabled)

    @property
    def enabled(self):
        return self.data["enabled"]

    @property
    def use_luna(self):
        return (self.enabled and monotonic() >= self.retry_at
                and not any(kind == "plan" and not future.done()
                            for kind, future in self.retired))

    def provider_failed(self, reason):
        self.provider_failures += 1
        self.retry_at = monotonic() + min(30, 2 ** min(self.provider_failures, 5))
        self.status = 'Laya fallback'
        self.owner._set_provider_event(reason + '; continuing with Laya')

    def invalidate(self):
        self.generation += 1
        if self.future:
            if not self.future.cancel():
                self.retired.append(("plan", self.future))
        self.future = None
        self.target = None
        self.facing = None
        self.data["plan"] = None
        if self.owner.decision_future:
            self.owner.decision_future.cancel()
        self.owner.decision_future = None
        self.owner.decision_key = None
        self.owner.held_action = None
        # Cancelled movement is not evidence that the destination is blocked.
        self.owner.last = None
        self.owner.cooldown = 0
        self.owner.navigation_target = None
        self.owner.opening_goal = None
        self.payload = None
        self.owner.memory.save()

    def toggle(self):
        self.data["enabled"] = not self.enabled
        self.invalidate()
        self.owner.screen_note = None
        self.owner.vision_key = None
        if self.owner.vision_future:
            if not self.owner.vision_future.cancel():
                self.retired.append(("screen", self.owner.vision_future))
        self.owner.vision_future = None
        self.status = "idle" if self.enabled else "off"
        record(self.owner.memory, "mode_change", self.status)
        self.owner._set_provider_event(f"Luna strategy {'On' if self.enabled else 'Off'}")

    def observe(self, state, entities, overworld, prompt_visible=None):
        self.poll_retired()
        if id(self.owner.memory.world) != self.world_id:
            self.world_id = id(self.owner.memory.world)
            self.observations = JourneyKnowledge(self.owner.memory)
            self.invalidate()
            self.goal = None
        current = self.owner.route.now
        key = (state.map_group, state.map_number)
        pending = self.observations.pending
        changed = self.observations.observe(state, entities, overworld=overworld,
                                            milestone=current, prompt_visible=prompt_visible)
        if current != self.goal or key != self.map_key:
            if self.goal is not None and current != self.goal:
                record(self.owner.memory, "milestone_change", str(current))
            if current != self.goal:
                self.maps_since_evidence.clear()
            elif overworld and key != self.map_key:
                self.maps_since_evidence.append(key)
                self.maps_since_evidence = self.maps_since_evidence[-12:]
            self.goal, self.map_key = current, key
            self.excluded.clear()
            self.invalidate()
        elif changed:
            # Seeing another sprite or another text page does not cancel a
            # committed route. Replan after the conversation actually closes.
            if ((pending and not self.observations.pending) or
                    (not self.target and not self.future and not self.observations.pending)):
                self.failures = 0
                self.owner.movement_history.points.clear()
                self.maps_since_evidence.clear()
                self.invalidate()
        if self.maps_since_evidence.count(key) >= 3:
            self.maps_since_evidence.clear()
            self.failed("Repeated map cycle without new dialogue or discoveries")
        if self.target and self.target["kind"] == "explore":
            if [state.x, state.y] == self.target["cell"]:
                record(self.owner.memory, "subgoal_completed", self.target["id"])
                self.failures = 0
                self.owner.movement_history.points.clear()
                self.invalidate()

    def failed(self, reason):
        if self.target:
            self.excluded.add(self.target["id"])
        self.failures += 1
        record(self.owner.memory, "loop_recovery", reason)
        self.invalidate()
        self.owner.movement_history.points.clear()
        if self.failures >= 4:
            self.owner.pause("Journey blocked after four distinct recovery plans. Retry or inspect the map.")

    def options(self, state, terrain):
        self.position = [state.x, state.y]
        if self.owner.movement_history.looping:
            self.failed("Repeated movement without new evidence")
        if self.owner.paused:
            return {}
        if self.target:
            result = target_options(self.target, state, self.owner.memory, terrain,
                                    self.observations.pending)
            if result:
                if self.target["kind"] == "talk" and "a" in result:
                    direction = self.target["direction"]
                    if self.facing != (self.target["id"], direction):
                        return {direction: "Face the sprite before speaking"}
                    return {"a": "Talk to the sprite"}
                return result
            if self.observations.pending:
                return {}
            self.failed("Target is no longer reachable")
            if self.owner.paused:
                return {}
        if self.future:
            if not self.future.done():
                if monotonic() - self.plan_started_at < 5:
                    return {}
                future, self.future = self.future, None
                if not future.cancel():
                    self.retired.append(("plan", future))
                self.provider_failed("Luna planning exceeded five seconds")
                return self.options(state, terrain)
            future, self.future = self.future, None
            try:
                plan, usage = future.result()
                plan = validate_plan(plan, self.payload)
                self.owner.usage.record("luna", **usage)
            except Exception as exc:
                detail = str(exc).strip().replace("\n", " ")[:120]
                suffix = f": {detail}" if detail else ""
                self.provider_failed(
                    f"Luna strategy unavailable: {type(exc).__name__}{suffix}")
                return self.options(state, terrain)
            self.target = next(c for c in self.payload["candidates"] if c["id"] == plan["target"])
            self.data["plan"] = plan
            self.status = "ready"
            self.provider_failures = 0
            record(self.owner.memory, "plan", plan["explanation"])
            self.owner._set_provider_event(f"Next: {plan['explanation']}")
            return self.options(state, terrain)
        available = candidates(
            state, self.owner.memory, terrain, excluded=self.excluded,
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
                state, self.owner.memory, terrain, excluded=self.excluded,
                reward_weights=self.owner.rewards.weights,
            )
        if not available:
            self.owner.pause("No reachable local leads or verified guide route. Inspect the map, then Retry.")
            return {}
        self.payload = self.context(state)
        self.payload["candidates"] = available
        milestone_reward = self.owner.rewards.weights["milestone"]
        runner_up = available[1].get("journey_reward", 0) if len(available) > 1 else -1
        if (available[0].get("journey_reward", 0) >= milestone_reward
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

    def chosen(self, action):
        if not self.target and not self.use_luna:
            self.target = getattr(self, "local_targets", {}).get(action)
        if not self.target:
            return
        if (action == self.target.get("direction") and self.target["kind"] == "talk"
                and self.position == self.target["cell"]):
            self.facing = self.target["id"], action
        if action == "a" and self.target["kind"] == "talk":
            self.observations.interacted(self.target["id"])
        record(self.owner.memory, "decision", action, target=self.target["id"])

    def context(self, state):
        return strategy_context(self, state)

    def poll_retired(self):
        """Count completed work without allowing stale answers to affect play."""
        for kind, future in self.retired[:]:
            if not future.done():
                continue
            self.retired.remove((kind, future))
            try:
                result = future.result()
                usage = result[1] if kind == "plan" else result.get("usage", {})
                self.owner.usage.record("luna", **usage)
            except Exception:
                pass  # Failed/cancelled requests have no confirmed usage payload.

    def summary(self):
        return strategy_summary(self)
