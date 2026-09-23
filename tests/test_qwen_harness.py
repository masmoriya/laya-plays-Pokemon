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
    assert strategy.enabled and not strategy.shared_control and strategy.required
    assert strategy.summary()['planner'] == 'Qwen'
    disabled = JourneyStrategy(controller, planner, enabled=False)
    assert not disabled.enabled


def test_qwen_holds_movement_until_current_plan_is_ready(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.data['enabled'] = True
    s = state()
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    strategy.observe(s, (sprite(),), True)
    candidate = {'id': 'priority', 'map': '09:02', 'kind': 'explore', 'cell': [2, 1],
                 'label': 'Follow the observed lead', 'completion': 'Arrive at tile',
                 'journey_reward': 5000, 'goal_route': True}
    alternative = {**candidate, 'id': 'alternative', 'cell': [1, 3], 'journey_reward': 1}
    monkeypatch.setattr('jpp.agent.journey_planning.candidates', lambda *a, **k: [candidate, alternative])
    monkeypatch.setattr('jpp.agent.journey_async.candidates', lambda *a, **k: [candidate, alternative])
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
    controller.map_state.update(
        s, Gold97CollisionMap((9, 2), 6, 6, bytes(36)), ready=True, overworld=True)
    calls = []
    pending = Future()
    def submit(*args):
        calls.append(args)
        return pending
    monkeypatch.setattr(controller.executor, 'submit', submit)
    assert strategy.options(s, Gold97CollisionMap((9, 2), 6, 6, bytes(36))) == {}
    assert calls[0][0] == strategy.provider.plan_visual
    assert calls[0][2] is not controller.planning_frame
    assert calls[0][4] is not None  # Qwen also receives the full navigation overview.
    assert controller.latest_model_input['context']['map_overview']['attached']
    assert controller.live.vision['status'] == 'analyzing'
    assert controller.live.vision['frame'].shape == (144, 160, 4)
    strategy.provider_failed('Vision unavailable')
    assert controller.live.vision['status'] == 'error'
    assert strategy.summary()['error'] == 'Vision unavailable'


def test_retired_plan_is_not_reported_as_a_vision_failure(controller):
    import numpy as np
    live = controller.live
    live.vision_started(np.zeros((144, 160, 4), dtype=np.uint8), {'state': {}})
    live.vision_retired('Navigation state changed; reply retired')
    assert live.vision['status'] == 'retired'
    assert live.vision['error'] == ''
    assert live.vision['result']['uncertainty'] == 'Navigation state changed; reply retired'


def test_qwen_plan_payload_contains_current_frame_as_image(monkeypatch):
    import numpy as np
    from PIL import Image
    provider = LocalJourneyProvider()
    captured = {}
    def structured(messages, schema, max_tokens):
        captured.update(messages=messages, schema=schema, max_tokens=max_tokens)
        return {'target': 'exit:next', 'explanation': 'Follow the observed exit',
                'evidence': ['exit:next'], 'completion': 'Observe arrival'}, {}
    monkeypatch.setattr(provider.client, 'structured', structured)
    payload = {'goal': 'Reach the next town', 'map': 'Route 118',
               'candidates': [{'id': 'exit:next', 'kind': 'exit', 'label': 'Go north',
                               'completion': 'Arrive at the next town'}]}
    frame = np.zeros((144, 160, 4), dtype=np.uint8)
    plan, _ = provider.plan_visual(payload, frame, map_overview=Image.new('RGB', (32, 16), 'black'))
    user_content = captured['messages'][0]['content']
    assert plan['target'] == 'exit:next'
    assert user_content[0]['type'] == 'text'
    image_parts = [part for part in user_content if part['type'] == 'image_url']
    assert len(image_parts) == 2
    assert 'Top-down observed map overview' in user_content[2]['text']
    image_part = image_parts[1]
    assert image_part['image_url']['url'].startswith('data:image/png;base64,')


def test_backend_world_party_and_map_survive_context_pressure(controller):
    from types import SimpleNamespace
    s = state()
    s.pokedex_species = ('UNKNOWN', 'VOLBEAR', 'HOPPIP')
    s.pokedex_caught_ids = (1, 2)
    s.pokedex_seen_ids = (1, 2, 3)
    s.owned_hms = ('Cut',)
    s.party = (SimpleNamespace(species='VOLBEAR', level=26, hp=74,
                               max_hp=80, status=None, moves=('CUT',),
                               types=('NORMAL',), stats=(55, 40, 36, 44, 45),
                               pp=(25,), max_pp=(25,), held_item='BERRY'),)
    controller.strategy.observe(s, (), True)
    payload = controller.strategy.context(s)
    payload['candidates'] = [{'id': f'c:{i}', 'label': 'route' * 60,
                              'completion': 'Arrive', 'journey_reward': 100-i}
                             for i in range(30)]
    payload['recent'] = ['old history' * 1000] * 30
    payload['navigation'] = {'position': [1, 1], 'fresh': True,
                             'exits': [[5, 1, 'right', 9, 7]]}
    payload['travel'] = {'destination': 'Rocket Ship Base', 'next_map': '13:0D',
                         'next_stop': 'Rocket Ship Base', 'route': [],
                         'exits': [{'to': '13:0D', 'name': 'Rocket Ship Base',
                                    'cell': [13, 5], 'direction': 'down'}]}
    payload['battle'] = {'kind': 'trainer', 'active': {'species': 'VOLBEAR',
                             'hp': 74, 'max_hp': 80, 'moves': ['CUT'], 'stats': [55,40,36,44,45]},
                        'opponent': {'species': 'BUGSYMON', 'hp': 20, 'max_hp': 20}}
    bounded = LocalJourneyProvider().model_input(payload)['state']
    assert bounded['world']['location']['position'] == [1, 1]
    assert bounded['world']['journey']['current'] == 6
    assert bounded['world']['pokedex']['caught_species'] == ['VOLBEAR', 'HOPPIP']
    assert bounded['world']['pokedex']['seen_count'] == 3
    assert bounded['party'][0]['moves'] == ['CUT']
    assert bounded['party'][0]['max_hp'] == 80
    assert bounded['party'][0]['stats'] == [55, 40, 36, 44, 45]
    assert bounded['party'][0]['max_pp'] == [25]
    assert bounded['battle']['opponent']['species'] == 'BUGSYMON'
    assert bounded['travel']['exits'][0]['cell'] == [13, 5]
    assert bounded['navigation']['exits'] == [[5, 1, 'right', 9, 7]]
    assert 'travel cost' in LocalJourneyProvider().model_input(payload)['prompt']


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


def test_stale_completed_plan_cannot_override_laya(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.provider.shared_control = True
    strategy.data['enabled'] = True
    s = state()
    strategy.observe(s, (sprite(),), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    options = strategy.options(s, terrain)
    candidate = strategy.payload['candidates'][0]
    strategy.chosen(next(iter(options)))
    local_target = strategy.target
    strategy.plan_identity = ('old', '09:02', 6, 'old')
    pending.set_result(({'target': candidate['id'], 'explanation': 'Old guidance',
                         'completion': 'Claim', 'evidence': [candidate['id']]}, {}))
    assert strategy.options(s, terrain)
    assert strategy.target == local_target
    assert strategy.data['selection_source'] == 'Route continuation'
    assert strategy.data['plan_review'] == 'State or evidence changed'
    assert any(row['kind'] == 'planner_rejected' for row in controller.memory.experience.recent())


def test_new_failure_rejects_pending_target(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.data['enabled'] = True
    s = state()
    strategy.observe(s, (sprite(),), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    strategy.options(s, terrain)
    target = strategy.payload['candidates'][0]
    controller.memory.experience.fail(6, target, 'Repeated movement without new evidence')
    pending.set_result(({'target': target['id'], 'explanation': 'Try again',
                         'completion': 'Claim', 'evidence': [target['id']]}, {}))
    strategy.poll_plan(s, terrain)
    assert strategy.target is None
    assert strategy.data['plan_review'] == 'Target no longer eligible'


def test_protected_memory_survives_qwen_context_pressure():
    summary = {'objective': 17, 'arrived_from': '09:08',
               'failed': ['gate: Repeated cycle'], 'recent': ['up: No transition'],
               'unresolved': ['Unknown exit at [2, 3]']}
    payload = {'goal': 'Reach Birdon', 'map': 'Westport City', 'navigation_memory': summary,
               'candidates': [{'id': 'exit:1', 'completion': 'Observe arrival'}],
               'clues': [], 'recent': ['History' * 1000] * 30}
    request = LocalJourneyProvider().model_input(payload)
    assert request['state']['navigation_memory'] == summary
    assert 'navigation_memory' in request['context']['retained_fields']
    assert 'recent' in request['context']['omitted_fields']


def test_late_qwen_target_does_not_reverse_a_committed_route(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.provider.shared_control = True
    strategy.data['enabled'] = True
    s = state()
    s.map_exits = ((0, 1, 'left', 9, 1), (5, 1, 'right', 9, 7))
    strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    options = strategy.options(s, terrain)
    assert 'left' in options and 'right' in options
    right = strategy.local_targets['right']
    left = strategy.local_targets['left']
    strategy.chosen('left')
    assert strategy.target['id'] == left['id']
    pending.set_result(({'target': right['id'], 'explanation': 'Investigate the east exit',
                         'completion': 'Claim', 'evidence': [right['id']]}, {}))
    assert strategy.options(s, terrain) == {'left': left['label']}
    assert strategy.target['id'] == left['id']
    assert strategy.data['selection_source'] == 'Route continuation'
    assert any(e['kind'] == 'planner_deferred' for e in controller.memory.experience.recent())


def test_same_map_waypoint_completion_preserves_pending_request(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.provider.shared_control = True
    strategy.data['enabled'] = True
    s = state()
    strategy.observe(s, (), True)
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    strategy.options(s, Gold97CollisionMap((9, 2), 6, 6, bytes(36)))
    payload, identity = strategy.payload, strategy.plan_identity
    strategy.invalidate(preserve_pending=True)
    assert strategy.future is pending and strategy.payload is payload
    assert strategy.request_identity(s) == identity


def test_pending_request_is_immutable_while_local_target_moves(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.provider.shared_control = True
    strategy.data['enabled'] = True
    s = state()
    strategy.observe(s, (sprite(),), True)
    pending = Future()
    monkeypatch.setattr(controller.executor, 'submit', lambda *a, **k: pending)
    strategy.options(s, Gold97CollisionMap((9, 2), 6, 6, bytes(36)))
    strategy.chosen(next(iter(strategy.local_targets)))
    original = next(c for c in strategy.payload['candidates'] if c['id'] == strategy.target['id'])
    cell = list(original['cell'])
    strategy.target['cell'] = [5, 5]
    assert original['cell'] == cell


def test_context_failure_is_visible_and_holds_movement(controller, monkeypatch):
    strategy = controller.strategy
    strategy.provider = LocalJourneyProvider()
    strategy.data['enabled'] = True
    strategy.observe(state(), (sprite(),), True)
    def too_large(payload):
        raise ValueError('Context exceeds budget')
    monkeypatch.setattr(strategy.provider, 'model_input', too_large)
    assert strategy.options(state(), Gold97CollisionMap((9, 2), 6, 6, bytes(36))) == {}
    assert strategy.future is None
    assert 'Context exceeds budget' in strategy.summary()['error']
