"""Planner ownership regressions; controlled futures never drive a real game."""
from concurrent.futures import Future

from test_journey_strategy import controller, state, sprite
from jpp.agent.journey_strategy import JourneyStrategy
from jpp.agent.local_vision import LocalJourneyProvider
from jpp.gold97_collision import Gold97CollisionMap


def test_local_launch_overrides_saved_disabled_planner(controller):
    controller.strategy.data['enabled'] = False
    planner = LocalJourneyProvider()
    strategy = JourneyStrategy(controller, planner, enabled=True)
    assert strategy.enabled and strategy.required
    assert strategy.summary()['planner'] == 'Qwen'
    disabled = JourneyStrategy(controller, planner, enabled=False)
    assert not disabled.enabled


def test_priority_target_waits_for_qwen_and_hands_off_plan(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.data['enabled'] = True
    s = state()
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    strategy.observe(s, (sprite(),), True)
    candidate = {'id': 'priority', 'map': '09:02', 'kind': 'explore', 'cell': [2, 1],
                 'label': 'Follow the observed lead', 'completion': 'Arrive at tile',
                 'journey_reward': 5000, 'goal_route': True}
    monkeypatch.setattr('jpp.agent.journey_planning.candidates', lambda *a, **k: [candidate])
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    assert strategy.options(s, terrain) == {}
    assert strategy.target is None
    assert strategy.future is pending
    assert controller.latest_model_input['provider'] == 'Qwen'
    pending.set_result(({'target': 'priority', 'explanation': 'Follow the observed lead',
                         'completion': 'invented', 'evidence': ['priority']}, {}))
    assert strategy.options(s, terrain)
    assert strategy.target == candidate
    assert strategy.summary()['plan']['completion'] == 'Arrive at tile'
    assert strategy.summary()['plan']['explanation'] == 'Follow the observed lead'
    strategy.invalidate()
    assert strategy.summary()['plan'] == {}
    assert strategy.summary()['last_response']['explanation'] == 'Follow the observed lead'


def test_qwen_failure_holds_movement_and_retries(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.data['enabled'] = True
    s = state()
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    strategy.observe(s, (sprite(),), True)
    failed = Future()
    failed.set_exception(RuntimeError('Model unavailable'))
    strategy.future = failed
    assert strategy.options(s, terrain) == {}
    assert strategy.status == 'retrying'
    assert strategy.target is None
    assert strategy.data['plan'] is None
    assert strategy.options(s, terrain) == {}
    strategy.retry_at = 0
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    assert strategy.options(s, terrain) == {}
    assert strategy.future is pending


def test_local_context_bounds_large_hm_history_without_mutating_input():
    from copy import deepcopy
    import json
    payload = {'goal': 'Find the missing child', 'map': 'Teknos City',
               'candidates': [{'id': f'target:{i}', 'kind': 'explore',
                               'label': 'Investigate', 'completion': 'Arrival',
                               'journey_reward': 100-i} for i in range(50)],
               'clues': [{'id': 'clue:1', 'text': 'Boulder Mines'}],
               'hm_journey': {'moves': ['irrelevant history' * 1000] * 8,
                              'instruction': 'Obtain Strength'},
               'recent': ['repeated movement' * 1000] * 50,
               'failed_attempts': [{'target': 'old', 'reason': 'loop'}]}
    original = deepcopy(payload)
    request = LocalJourneyProvider().model_input(payload)
    assert len(request['prompt']) < 7100
    assert len(json.dumps(request['state'])) < 6600
    assert request['state']['hm_journey']['instruction'] == 'Obtain Strength'
    assert request['state']['failed_attempts'][0]['reason'] == 'loop'
    assert request['state']['candidates'][0]['id'] == 'target:0'
    assert payload == original


def test_planner_dispatch_includes_copied_game_frame(controller, monkeypatch):
    import numpy as np
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.data['enabled'] = True
    s = state()
    strategy.observe(s, (sprite(),), True)
    controller.planning_frame = np.zeros((144, 160, 4), dtype=np.uint8)
    calls = []
    pending = Future()
    def submit(*args):
        calls.append(args)
        return pending
    monkeypatch.setattr(controller.executor, 'submit', submit)
    assert strategy.options(s, Gold97CollisionMap((9, 2), 6, 6, bytes(36))) == {}
    assert calls[0][0] == strategy.provider.plan_visual
    assert calls[0][2] is not controller.planning_frame
    assert controller.live.vision['status'] == 'analyzing'
    assert controller.live.vision['frame'].shape == (144, 160, 4)
    strategy.provider_failed('Vision unavailable')
    assert controller.live.vision['status'] == 'error'
    assert strategy.summary()['error'] == 'Vision unavailable'


def test_backend_world_party_and_map_survive_context_pressure(controller):
    from types import SimpleNamespace
    s = state()
    s.pokedex_species = ('UNKNOWN', 'VOLBEAR', 'HOPPIP')
    s.pokedex_caught_ids = (1, 2)
    s.pokedex_seen_ids = (1, 2, 3)
    s.owned_hms = ('Cut',)
    s.party = (SimpleNamespace(species='VOLBEAR', level=26, hp=74,
                               max_hp=80, status=None, moves=('CUT',)),)
    controller.strategy.observe(s, (), True)
    payload = controller.strategy.context(s)
    payload['candidates'] = [{'id': f'c:{i}', 'label': 'route' * 60,
                              'completion': 'Arrive', 'journey_reward': 100-i}
                             for i in range(30)]
    payload['recent'] = ['old history' * 1000] * 30
    payload['navigation'] = {'position': [1, 1], 'fresh': True,
                             'exits': [[5, 1, 'right', 9, 7]]}
    bounded = LocalJourneyProvider().model_input(payload)['state']
    assert bounded['world']['location']['position'] == [1, 1]
    assert bounded['world']['journey']['current'] == 6
    assert bounded['world']['pokedex']['caught_species'] == ['VOLBEAR', 'HOPPIP']
    assert bounded['world']['pokedex']['seen_count'] == 3
    assert bounded['party'][0]['moves'] == ['CUT']
    assert bounded['party'][0]['max_hp'] == 80
    assert bounded['navigation']['exits'] == [[5, 1, 'right', 9, 7]]


def test_verified_mine_guidance_reaches_local_planner(controller):
    from jpp.route_progress import RouteProgress
    s = state()
    s.map_group, s.map_number, s.area_name = 4, 5, 'Teknos City'
    s.mechanics_verified = True
    controller.route = RouteProgress(set(range(1, 12)))
    payload = controller.strategy.context(s)
    payload['candidates'] = [{'id': 'mine', 'label': 'Approach mine',
                              'completion': 'Arrive'}]
    bounded = LocalJourneyProvider().model_input(payload)['state']
    guidance = bounded['world']['journey']['guidance']
    assert 'girl' in guidance['instruction']
    assert '1F' in guidance['instruction']
    assert 'rescue event flag' in guidance['completion']
