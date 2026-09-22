"""Event-driven journey planning shared by live and headless controllers."""

from time import monotonic, time
from .journey_context import strategy_context, strategy_summary
from .journey_knowledge import JourneyKnowledge, knowledge, record
from .journey_strategy_provider import JourneyStrategyProvider, validate_plan
from .journey_targets import target_options
from .journey_planning import JourneyPlanning
from .journey_observation import JourneyObservation


class JourneyStrategy(JourneyObservation, JourneyPlanning):
    def __init__(self, controller, provider=None, enabled=True):
        from .field_actions import FieldAction
        self.field_action = FieldAction()
        self.owner = controller
        self.default_enabled = enabled
        self.provider = provider or JourneyStrategyProvider()
        data = knowledge(controller.memory, enabled)
        if getattr(self.provider, "required", False):
            data["enabled"] = enabled
            data["plan"] = None
        self.observations = JourneyKnowledge(controller.memory)
        self.future = None
        self.generation = 0
        self.goal = None
        self.map_key = None
        self.arrived_from = None
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
        self.last_transition_target = None
        self.recovery_retry_at = 0

    @property
    def label(self):
        return getattr(self.provider, "label", "Luna")

    @property
    def required(self):
        return self.enabled and getattr(self.provider, "required", False)

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
        self.last_error = reason
        if getattr(self, "plan_has_image", False):
            self.owner.live.vision_finished(error=reason)
        self.provider_failures += 1
        self.retry_at = monotonic() + min(30, 2 ** min(self.provider_failures, 5))
        self.status = 'retrying' if self.required else 'Laya fallback'
        suffix = '; movement held; retrying planner' if self.required else '; continuing with Laya'
        self.owner._set_provider_event(reason + suffix)

    def invalidate(self):
        self.recovery_retry_at = 0
        self.generation += 1
        if self.future:
            if not self.future.cancel():
                self.retired.append(("plan", self.future))
        self.future = None
        self.target = None
        self.warp_wait = 0
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
        self.owner._set_provider_event(f"{self.label} strategy {'On' if self.enabled else 'Off'}")

    def failed(self, reason):
        target = self.target or self.last_transition_target
        if target:
            from .navigation_trace import record_target
            record_target(self.owner.memory, target)
            npc = self.data['npcs'].get(target['id'])
            if npc and npc.get('category') in {'item', 'obstacle'}:
                from .object_memory import attempt, evidence_key
                attempt(npc, evidence_key(self.observations.state, npc, self.owner.memory), 'approach')
            self.excluded.add(target["id"])
            self.owner.memory.experience.fail(self.owner.route.now, target, reason)
        self.failures += 1
        record(self.owner.memory, "loop_recovery", reason)
        self.invalidate()
        self.owner.movement_history.points.clear()
        self.last_transition_target = None
        self.status = "recovering"
        self.owner._set_provider_event("Replanning toward the current journey objective")

    def options(self, state, terrain):
        self.position = [state.x, state.y]
        failures = self.owner.memory.experience.failures(self.owner.route.now)
        transient = {"Target is no longer reachable", "Repeated movement without new evidence",
                     "Repeated map cycle without new dialogue or discoveries"}
        expired = [item for item in failures if item["reason"] in transient
                   and time() - item.get("timestamp", 0) >= 60]
        self.excluded.difference_update(item["target"] for item in expired)
        durable = {key for item in failures if item not in expired
                   for key in (item['target'], item['target_key'])}
        if self.owner.movement_history.looping:
            self.failed("Repeated movement without new evidence")
        if self.owner.paused:
            return {}
        if not self.observations.pending:
            self.reconsider_obstacle(state, terrain, durable)
        if self.target:
            result = target_options(self.target, state, self.owner.memory, terrain,
                                    self.observations.pending)
            if result:
                if self.target["kind"] == "talk" and "a" in result:
                    direction = self.target["direction"]
                    settle = (self.target['id'], tuple(self.position), direction)
                    if getattr(self, 'interaction_arrival', None) != settle:
                        self.interaction_arrival, self.interaction_ticks = settle, 0
                        self.facing = None
                    if self.interaction_ticks < 24:
                        self.interaction_ticks += 1
                        self.owner.held_action = None
                        self.owner.last = None
                        return {}
                    observed_facing = getattr(state, 'player_facing', None)
                    if (observed_facing != direction if observed_facing is not None
                            else self.facing != (self.target["id"], direction)):
                        return {direction: "Face the sprite before speaking"}
                    npc = self.data['npcs'][self.target['id']]
                    if npc.get('category') == 'obstacle' and npc.get('outcome') == 'unresolved':
                        from .field_actions import strength_push
                        if strength_push(state, npc, self.owner.memory):
                            return {direction: 'Push the obstacle with active Strength'}
                        from .field_actions import experiments
                        if experiments(state, npc, self.owner.memory):
                            return {'start': 'Inspect a party field move for this obstacle'}
                    return {"a": (self.target["label"] if npc.get("category") in {"item", "obstacle"}
                                  else "Talk to the sprite")}
                self.interaction_arrival = None
                self.facing = None
                return result
            if self.observations.pending:
                return {}
            if (self.target["kind"] == "exit" and not self.target.get("direction")
                    and self.position == self.target["cell"]):
                # Coordinates arrive before a stair/door animation completes.
                # Keep ownership until its observed transition, rather than
                # declaring the successful approach unreachable and walking back.
                self.warp_wait = getattr(self, "warp_wait", 0) + 1
                if self.warp_wait <= 90:
                    self.owner.held_action = None
                    return {}
            self.warp_wait = 0
            self.failed("Target is no longer reachable")
            if self.owner.paused:
                return {}
        if self.future:
            if not self.future.done():
                deadline = getattr(self.provider, 'timeout', 60)
                if monotonic() - self.plan_started_at < deadline:
                    return {}
                future, self.future = self.future, None
                if not future.cancel():
                    self.retired.append(("plan", future))
                self.owner.memory.experience.record('planner_timeout', deadline=deadline)
                self.provider_failed(f"{self.label} planning exceeded {deadline:g} seconds")
                return self.options(state, terrain)
            future, self.future = self.future, None
            try:
                plan, usage = future.result()
                plan = validate_plan(plan, self.payload)
                self.owner.usage.record("luna", **usage)
                self.owner.live.model_call(
                    "luna", usage, self.owner.latest_model_input, phase="strategy"
                )
            except Exception as exc:
                detail = str(exc).strip().replace("\n", " ")[:120]
                suffix = f": {detail}" if detail else ""
                self.provider_failed(
                    f"{self.label} strategy unavailable: {type(exc).__name__}{suffix}")
                self.owner.live.model_call(
                    "luna", status="error", error=detail, phase="strategy"
                )
                return self.options(state, terrain)
            self.target = next(c for c in self.payload["candidates"] if c["id"] == plan["target"])
            self.data["plan"] = plan
            self.accepted_dialogue_key = getattr(self, "plan_dialogue_key", None)
            self.data["last_response"] = {**plan, "goal": self.payload.get("goal")}
            self.owner.memory.experience.record('planner_accepted', plan=plan, usage=usage)
            self.status = "ready"
            self.last_error = ""
            if getattr(self, "plan_has_image", False):
                self.owner.live.vision_finished({"mode": "planning", "screen_text": [],
                                                "uncertainty": plan["explanation"]})
            self.provider_failures = 0
            record(self.owner.memory, "plan", plan["explanation"])
            self.owner._set_provider_event(f"{self.label} -> Laya: {plan['explanation']}")
            return self.options(state, terrain)
        return self.plan_next(state, terrain, durable)

    def chosen(self, action):
        if not self.target and not self.use_luna:
            self.target = getattr(self, "local_targets", {}).get(action)
        if not self.target:
            return
        from .exploration_cycles import evidence
        self.target.setdefault('evidence_at_start', repr(evidence(self.owner.memory)))
        if (action == self.target.get("direction") and self.target["kind"] == "talk"
                and self.position == self.target["cell"]):
            self.facing = self.target["id"], action
            from .field_actions import record_push
            record_push(self.observations.state, self.data['npcs'][self.target['id']], self.owner.memory, action)
        if action == 'start' and self.target['kind'] == 'talk':
            self.field_action.start(self.observations.state, self.data['npcs'][self.target['id']], self.owner.memory)
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
