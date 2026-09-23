"""Navigation evidence and exclusions survive time, ranking, and recovery."""
from test_journey_strategy import controller, state
from jpp.agent.navigation_memory import allowed_targets, navigation_memory, target_evidence
from jpp.agent.exploration_cycles import filter_cycles, record_transition
from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap


def gate(x=2):
    return dict(id=f'gate:{x}', kind='exit', map='09:02', cell=[x, 0], direction='up',
                destination_key='09:08', label='Gate', completion='Observe transition',
                goal_route=True, journey_reward=400)


def test_cycle_failure_excludes_only_the_failed_approach(controller):
    s = state()
    controller.strategy.observe(s, (), True)
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle without new discoveries')
    other = {**gate(5), 'id': 'other'}
    assert allowed_targets(controller.memory, 6, [gate(), gate(3), other]) == [other]
    assert allowed_targets(controller.memory, 7, [gate()])
    controller.memory.experience.retry(6)
    assert allowed_targets(controller.memory, 6, [gate(), gate(3)])


def test_cycle_failure_does_not_hide_the_required_next_route_hop(controller):
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle without new discoveries')
    assert allowed_targets(controller.memory, 6, [gate()], preserve_cycles_to='09:08') == [gate()]
    assert not allowed_targets(controller.memory, 6, [gate()], preserve_cycles_to='09:07')


def test_required_route_can_return_through_the_arrival_gate(controller):
    from jpp.agent.passage_navigation import mark_entry_returns
    controller.memory.world['navigation_arrival'] = {
        'map': '09:02', 'from': '09:08', 'goal': 6, 'cell': [2, 1]}
    target = gate()
    assert mark_entry_returns([target], controller.memory, state(), 6,
                              required_next_map='09:08') == [target]
    assert not target.get('recent_return')


def test_blocked_tile_does_not_exclude_neighboring_door(controller):
    controller.memory.experience.fail(6, gate(), 'Target is no longer reachable')
    assert allowed_targets(controller.memory, 6, [gate(), gate(3)]) == [gate(3)]


def test_elapsed_time_and_incidental_clues_do_not_release_failure(controller):
    controller.strategy.observe(state(), (), True)
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle')
    controller.strategy.data['clues'].append({'map': '09:02', 'text': 'Books are fun.'})
    assert not allowed_targets(controller.memory, 6, [gate()])
    controller.strategy.data['clues'].append({'map': '09:02', 'text': 'The gate is unlocked.'})
    assert allowed_targets(controller.memory, 6, [gate()])
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle')
    assert not allowed_targets(controller.memory, 6, [gate()])


def test_failures_are_enforced_after_ranking_and_during_recovery(controller):
    s = state()
    s.map_exits = ((2, 0, 'up', 9, 8), (3, 0, 'up', 9, 8), (5, 1, 'right', 9, 7))
    controller.strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle')
    assert all(t.get('destination_key') != '09:08' for t in candidates(s, controller.memory, terrain))
    assert all(t.get('destination_key') != '09:08' for t in controller.strategy.recovery_candidates(s, terrain))


def test_transition_budget_counts_both_gate_entrances(controller):
    for x in (2, 3, 2):
        record_transition(controller.memory, '09:02', [x, 0], '09:08')
    assert filter_cycles([gate(), gate(3)], controller.memory) == []
    assert filter_cycles([gate(5)], controller.memory)


def test_memory_contains_real_outcomes_and_unknown_exit_stays_unknown(controller):
    s = state()
    controller.strategy.observe(s, (), True)
    controller.strategy.arrived_from = '09:08'
    controller.memory.experience.action(s, 'right', 'Laya', 6)
    s.x += 1
    controller.memory.experience.observe(s)
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle')
    memory = navigation_memory(controller.strategy, s)
    assert memory['objective'] == 6 and memory['arrived_from'] == '09:08'
    assert memory['recent'] == ['right: Moved [1, 1] to [2, 1]']
    assert memory['failed']
    assert target_evidence({**gate(), 'destination_key': '00:00'}, controller.memory) == 'observed exit; destination unknown'


def test_observed_unknown_exit_retains_its_learned_destination(controller):
    from jpp.agent.journey_exits import exit_candidates
    s = state()
    s.map_exits = ((2, 0, 'up', 0, 0),)
    controller.strategy.data['connections'] = [
        {'from': '09:02', 'at': [2, 0], 'to': '09:08', 'arrival': [4, 7], 'direction': 'up'}]
    tasks = exit_candidates(s, controller.memory, {(2, 0): 'up'}, ())
    assert len(tasks) == 1
    assert tasks[0]['destination_key'] == '09:08'
    assert target_evidence(tasks[0], controller.memory) == 'observed traversal'


def test_destination_alias_cannot_bypass_failed_activation(controller):
    unknown = {**gate(), 'destination_key': '00:00', 'id': 'unknown'}
    controller.memory.experience.fail(6, unknown, 'Target is no longer reachable')
    assert not allowed_targets(controller.memory, 6, [gate()])


def test_exhausted_failures_are_retried_once_per_position_and_evidence(controller, monkeypatch):
    s = state()
    controller.strategy.observe(s, (), True)
    controller.memory.experience.fail(6, gate(), 'Repeated map cycle')
    retries = []
    original = controller.memory.experience.retry
    def retry(goal):
        retries.append(goal)
        original(goal)
    monkeypatch.setattr(controller.memory.experience, 'retry', retry)
    monkeypatch.setattr('jpp.agent.journey_planning.candidates', lambda *a, **k: [])
    monkeypatch.setattr(controller.strategy, 'recovery_candidates', lambda *a: [])
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    controller.strategy.recovery_retry_at = 0
    controller.strategy.plan_next(s, terrain, set())
    controller.strategy.recovery_retry_at = 0
    controller.strategy.plan_next(s, terrain, set())
    assert retries == [6]
