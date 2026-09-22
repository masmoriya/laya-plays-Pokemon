"""Recovery keeps the journey running without forgetting failed approaches."""
from test_journey_strategy import controller, state

from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap


def test_exhausted_leads_retry_oldest_and_preserve_failures(controller):
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
    failures = controller.memory.experience.failures(controller.route.now)
    assert strategy.options(s, terrain)
    assert not controller.paused
    assert {t['id'] for t in strategy.payload['candidates']} == {tasks[0]['id']}
    assert controller.memory.experience.failures(controller.route.now) == failures
    strategy.chosen(next(iter(strategy.local_targets)))
    strategy.failed('Still blocked')
    assert strategy.options(s, terrain)
    assert strategy.payload['candidates'][0]['id'] == tasks[1]['id']
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
