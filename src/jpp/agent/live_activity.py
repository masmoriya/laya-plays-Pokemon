"""Visible activity derived from actual running work, never invented reasoning."""
from time import monotonic
from ..route_progress import MAIN


def activity(owner):
    state = getattr(owner, 'latest_observed_state', None)
    work = None
    if not owner.paused:
        for future, provider, phase in (
            (owner.decision_future, owner._provider_label(), 'Choosing an action'),
            (owner.strategy.future, getattr(owner.strategy, 'label', 'Luna'), 'Planning the next task'),
            (owner.vision_future, getattr(owner.strategy, 'label', 'Luna'), 'Reading the screen'),
        ):
            if future is not None and not future.done():
                work = future, provider, phase
                break
    if work:
        future, provider, phase = work
        if getattr(owner, '_visible_work', None) is not future:
            owner._visible_work, owner._visible_work_started = future, monotonic()
        payload = owner.strategy.payload or {}
        tasks = [c.get('label', c['id']) for c in payload.get('candidates', [])]
        if future is owner.decision_future:
            tasks = list(getattr(owner, 'pending_options', {}).values())
        tasks = list(dict.fromkeys(tasks))[:3]
        return {'kind': 'thinking', 'provider': provider, 'phase': phase,
                'elapsed_seconds': monotonic() - owner._visible_work_started,
                'goal': MAIN.get(owner.route.now, 'Continue journey'), 'options': tasks}
    owner._visible_work = None
    if owner.paused:
        return {'kind': 'paused', 'phase': owner.pause_reason}
    if owner.provider_health != 'ready' and not getattr(state, 'in_battle', False):
        return {'kind': 'waiting', 'phase': 'Connecting to Laya'}
    return {'kind': 'executing' if owner.held_action else 'waiting',
            'phase': 'Executing controls' if owner.held_action else 'Observing game response'}
