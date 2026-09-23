"""Recovery keeps the journey running without forgetting failed approaches."""
from test_journey_strategy import controller, state

from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap


def test_exhausted_leads_are_reopened_once_for_a_fresh_route_attempt(controller):
    strategy = controller.strategy
    s = state()
    strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    controller.memory.map("09:02")["visited"] = [[x, y] for x in range(6) for y in range(6)]
    s.map_exits = ((0, 1, "left", 9, 1), (5, 1, "right", 9, 7))
    tasks = candidates(s, controller.memory, terrain)
    assert len(tasks) > 1
    for target in tasks:
        strategy.target = target
        strategy.failed('Movement loop')
    assert strategy.options(s, terrain)
    assert strategy.status == 'ready'
    assert not controller.paused
    assert controller.memory.experience.failures(controller.route.now) == []
    assert strategy.options(s, terrain)
    assert controller.route.now == 6


def test_exhausted_known_ground_stops_instead_of_wandering(controller):
    strategy = controller.strategy
    s = state()
    strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    controller.memory.map('09:02')['visited'] = [[x, y] for x in range(6) for y in range(6)]
    assert not candidates(s, controller.memory, terrain)
    assert not strategy.options(s, terrain)
    assert strategy.status == 'blocked'
    assert 'No untried reachable' in strategy.summary()['next']
    assert not controller.paused
    assert controller.route.now == 6


def test_planner_waits_for_current_map_collision_snapshot(controller, monkeypatch):
    strategy = controller.strategy
    s = state()
    s.mechanics_verified = True
    strategy.observe(s, (), True)
    monkeypatch.setattr(
        'jpp.agent.journey_planning.candidates',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('planning must wait until collision terrain is current')),
    )

    assert strategy.plan_next(s, None, set()) == {}
    assert strategy.status == 'waiting_for_terrain'
    assert strategy.future is None
    assert strategy.data['plan'] is None


def test_single_route_frontier_stays_committed_across_replanning(controller, monkeypatch):
    strategy = controller.strategy
    strategy.toggle()
    s = state()
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    strategy.observe(s, (), True)
    frontier = {'id': 'explore:route-frontier', 'kind': 'explore',
                'cell': [2, 1], 'direction': '', 'map': '09:02',
                'label': 'Explore toward next route',
                'completion': 'Reach the target tile',
                'travel_route': True, 'goal_route': True, 'journey_reward': 200}
    monkeypatch.setattr('jpp.agent.journey_planning.candidates',
                        lambda *args, **kwargs: [dict(frontier)])

    assert strategy.plan_next(s, terrain, set()) == {'right': 'Explore toward next route'}
    assert strategy.target['id'] == frontier['id']
    assert strategy.data['selection_source'] == 'Route continuation'

    # The currently exposed camera frontier moves as the player walks, but the
    # selected waypoint is retained until it is reached and observed.
    s.y = 2
    assert strategy.options(s, terrain)
    assert strategy.target['id'] == frontier['id']
    s.x, s.y = 2, 1
    strategy.observe(s, (), True)
    assert strategy.target is None


def test_qwen_reply_keeps_required_next_gate_despite_adjacent_cycle_failure(controller, monkeypatch):
    from concurrent.futures import Future
    from jpp.route_progress import RouteProgress

    strategy = controller.strategy
    strategy.toggle()
    controller.route = RouteProgress(set(range(1, 22)))
    controller.memory.world['route'] = controller.route.to_dict()
    s = state()
    s.map_group, s.map_number = 2, 3
    s.x, s.y = 3, 13
    s.map_width, s.map_height = 20, 18
    s.mechanics_verified = True
    strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((2, 3), 20, 18, bytes(360))
    failed = {'id': 'geometry:02:03:0:9:left', 'kind': 'exit',
              'cell': [0, 9], 'direction': 'left', 'map': '02:03',
              'destination_key': '02:08', 'label': 'Route 118 gate'}
    controller.memory.experience.fail(22, failed, 'Repeated map cycle without new dialogue')
    target = {'id': 'geometry:02:03:0:10:02:08', 'kind': 'exit',
              'cell': [0, 10], 'direction': 'left', 'map': '02:03',
              'destination_key': '02:08', 'label': 'Travel to Route 118',
              'completion': 'Observe arrival in Route 118'}
    monkeypatch.setattr('jpp.agent.journey_async.candidates',
                        lambda *args, **kwargs: [dict(target)])
    strategy.payload = {'candidates': [target], 'clues': [],
                        'goal': 'Continue toward Sunpoint City'}
    strategy.future = Future()
    strategy.future.set_result(({'target': target['id'], 'explanation': 'Use Route 118',
                                 'evidence': [target['id']],
                                 'completion': target['completion']}, {'input_tokens': 1}))
    strategy.plan_identity = strategy.request_identity(s)

    assert strategy.future.done()
    strategy.poll_plan(s, terrain)

    assert strategy.future is None
    assert strategy.target is not None, strategy.data.get('plan_review')
    assert strategy.target['id'] == target['id']
    assert strategy.data['plan_review'] == 'Accepted against current reachable targets'
