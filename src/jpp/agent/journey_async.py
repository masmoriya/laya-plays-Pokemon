"""Accept asynchronous plans only against current, legal navigation evidence."""
from time import monotonic

from .journey_strategy_provider import validate_plan
from .journey_targets import candidates, target_options
from .navigation_memory import allowed_targets, evidence_stamp
from .journey_knowledge import record
from .navigation_policy import preferred_targets, preserves_commitment


class JourneyAsync:
    @property
    def shared_control(self):
        return bool(self.enabled and getattr(self.provider, 'shared_control', False))

    def request_identity(self, state):
        key = f'{state.map_group:02X}:{state.map_number:02X}'
        return (self.generation, key, self.owner.route.now,
                evidence_stamp(self.owner.memory, self.owner.route.now, key))

    def poll_plan(self, state, terrain):
        if not self.future:
            return
        future = self.future
        if not future.done():
            deadline = getattr(self.provider, 'timeout', 60)
            if monotonic() - self.plan_started_at < deadline:
                return
            self.future = None
            if not future.cancel():
                self.retired.append(('plan', future))
            self.owner.memory.experience.record('planner_timeout', deadline=deadline,
                                                plan_id=getattr(self, 'plan_id', None))
            self.provider_failed(f'{self.label} planning exceeded {deadline:g} seconds')
            return
        # Never change direction in a walking animation or interrupt an interaction.
        if getattr(state, 'player_moving', False) or self.observations.pending:
            return
        self.future = None
        try:
            plan, usage = future.result()
            self.owner.usage.record('luna', **usage)
            submitted = getattr(self, 'submitted_input', None) or self.owner.latest_model_input
            self.owner.live.model_call('luna', usage, submitted, phase='strategy')
            plan = validate_plan(plan, self.payload)
        except Exception as exc:
            detail = str(exc).strip().replace('\n', ' ')[:120]
            self.provider_failed(f'{self.label} strategy unavailable: {type(exc).__name__}: {detail}')
            self.owner.live.model_call('luna', status='error', error=detail, phase='strategy')
            return
        current = candidates(state, self.owner.memory, terrain,
                             excluded=self.excluded, reward_weights=self.owner.rewards.weights)
        current = allowed_targets(self.owner.memory, self.owner.route.now, current)
        target = next((c for c in current if c['id'] == plan['target']), None)
        if target is None:
            # Moving the camera can change the representative frontier shortlist
            # without making a submitted, still-unvisited viewpoint invalid.
            submitted_target = next(c for c in self.payload['candidates'] if c['id'] == plan['target'])
            from .navigation_trace import unexhausted
            visited = self.owner.memory.map(submitted_target.get('map', ''))['visited']
            if (submitted_target['kind'] == 'explore' and submitted_target['cell'] not in visited
                    and not submitted_target.get('reobserve_interaction')
                    and submitted_target['id'] not in self.excluded
                    and allowed_targets(self.owner.memory, self.owner.route.now, [submitted_target])
                    and unexhausted(self.owner.memory, [submitted_target])
                    and target_options(submitted_target, state, self.owner.memory, terrain)):
                target = submitted_target
        identity = getattr(self, 'plan_identity', self.request_identity(state))
        if identity != self.request_identity(state) or target is None:
            reason = 'State or evidence changed' if identity != self.request_identity(state) else 'Target no longer eligible'
            self.data['plan_review'] = reason
            self.owner.memory.experience.record('planner_rejected', plan=plan,
                                                plan_id=getattr(self, 'plan_id', None), reason=reason)
            if getattr(self, 'plan_has_image', False):
                self.owner.live.vision_finished(error=reason)
            self.status = 'reconsidering'
            return
        if preserves_commitment(self.target, target, state, self.owner.memory, terrain):
            reason = 'Finish the active reachable target before changing routes'
            self.data['plan_review'] = reason
            self.owner.memory.experience.record('planner_deferred', plan=plan,
                                                plan_id=getattr(self, 'plan_id', None), reason=reason)
            self.status, self.last_error, self.provider_failures = 'ready', '', 0
            if getattr(self, 'plan_has_image', False):
                self.owner.live.vision_finished({'mode': 'planning', 'screen_text': [],
                                                'uncertainty': reason})
            return
        self.owner.decision_future = None
        self.owner.decision_key = None
        self.owner.held_action = None
        self.owner.last = None
        self.owner.cooldown = 0
        self.generation += 1
        self.target = target
        self.data['selection_source'] = self.label
        self.data['plan_review'] = 'Accepted against current reachable targets'
        self.data['plan_id'] = getattr(self, 'plan_id', None)
        self.data['plan'] = plan
        self.accepted_dialogue_key = getattr(self, 'plan_dialogue_key', None)
        self.data['last_response'] = {**plan, 'goal': self.payload.get('goal')}
        self.owner.memory.experience.record('planner_accepted', plan=plan, usage=usage,
                                            plan_id=getattr(self, 'plan_id', None), source=self.label)
        self.status, self.last_error, self.provider_failures = 'ready', '', 0
        if getattr(self, 'plan_has_image', False):
            self.owner.live.vision_finished({'mode': 'planning', 'screen_text': [],
                                            'uncertainty': plan['explanation']})
        record(self.owner.memory, 'plan', plan['explanation'])
        self.owner._set_provider_event(f"{self.label} -> Laya: {plan['explanation']}")

    def local_options(self, state, terrain, available=None):
        if available is None:
            available = candidates(state, self.owner.memory, terrain,
                                   excluded=self.excluded, reward_weights=self.owner.rewards.weights)
            available = self.prioritize_forward_routes(available)
        available = allowed_targets(self.owner.memory, self.owner.route.now, available)
        available = preferred_targets(available)
        from .journey_targets import target_options
        options, self.local_targets = {}, {}
        for target in available:
            for action, label in target_options(target, state, self.owner.memory, terrain).items():
                if action == 'a':
                    continue  # Commit the approach before facing/speaking.
                options.setdefault(action, label)
                self.local_targets.setdefault(action, target)
        return options
