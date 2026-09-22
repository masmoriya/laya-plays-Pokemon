"""Reacquiring an unknown object must lead to an observed interaction."""
from test_journey_strategy import controller, state, sprite
from jpp.agent.journey_targets import candidates, target_options
from jpp.gold97_collision import Gold97CollisionMap


def remembered(controller):
    s = state()
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    controller.strategy.observe(s, (sprite(),), True)
    obj = next(iter(controller.strategy.data['npcs'].values()))
    obj['visible'] = False
    target = next(t for t in candidates(s, controller.memory, terrain)
                  if t['id'] == obj['id'])
    controller.strategy.target = target
    return s, terrain, obj, target


def test_reacquired_unknown_becomes_interaction_before_arrival(controller):
    s, terrain, obj, target = remembered(controller)
    controller.strategy.observe(s, (sprite(),), True)
    assert controller.strategy.target is target
    assert target['kind'] == 'talk'
    assert not target['reobserve_interaction']
    s.x, s.y = target['cell']
    s.player_facing = target['direction']
    for _ in range(25):
        options = controller.strategy.options(s, terrain)
    assert options == {'a': 'Talk to the sprite'}
    controller.strategy.chosen('a')
    assert controller.strategy.observations.pending['id'] == obj['id']
    assert obj['outcome'] == 'seen'


def test_reacquired_at_arrival_is_not_completed_as_exploration(controller):
    s, terrain, obj, target = remembered(controller)
    s.x, s.y = target['cell']
    controller.strategy.observe(s, (sprite(),), True)
    assert controller.strategy.target is target
    assert 'a' in target_options(target, s, controller.memory, terrain)


def test_reacquired_moving_object_updates_approach(controller):
    s, terrain, obj, target = remembered(controller)
    obj.update(visible=True, cell=[4, 1])
    target_options(target, s, controller.memory, terrain)
    assert target['kind'] == 'talk'
    assert target['cell'] == [3, 1]


def test_unseen_object_does_not_become_blind_interaction(controller):
    s, terrain, obj, target = remembered(controller)
    target_options(target, s, controller.memory, terrain)
    assert target['kind'] == 'explore'
    assert target['reobserve_interaction']


def test_exploration_stops_for_adjacent_unvisited_object(controller):
    s, terrain, obj, target = remembered(controller)
    obj['visible'] = True
    s.x, s.y = 2, 1
    controller.strategy.target = {
        'id': 'explore:09:02:(5, 5)', 'kind': 'explore', 'cell': [5, 5],
        'map': '09:02', 'direction': '', 'label': 'Investigate unexplored ground'}
    controller.strategy.options(s, terrain)
    assert controller.strategy.target['id'] == obj['id']
    assert controller.strategy.target['kind'] == 'talk'


def test_distant_unrelated_object_does_not_interrupt_exploration(controller):
    s, terrain, obj, target = remembered(controller)
    obj['visible'] = True
    controller.strategy.target = {
        'id': 'explore:09:02:(5, 5)', 'kind': 'explore', 'cell': [5, 5],
        'map': '09:02', 'direction': '', 'label': 'Investigate unexplored ground'}
    controller.strategy.reconsider_interaction(s, terrain, set())
    assert controller.strategy.target['kind'] == 'explore'


def test_arrival_waits_for_sprite_before_recording_failure(controller):
    s, terrain, obj, target = remembered(controller)
    s.x, s.y = target['cell']
    for _ in range(12):
        controller.strategy.observe(s, (), True)
        assert controller.strategy.options(s, terrain) == {}
        assert controller.strategy.target is target
    controller.strategy.observe(s, (sprite(),), True)
    assert controller.strategy.target is target
    assert target['kind'] == 'talk'
    assert not controller.memory.experience.failures(controller.route.now)


def test_settled_missing_sprite_eventually_fails(controller):
    s, terrain, obj, target = remembered(controller)
    s.x, s.y = target['cell']
    for _ in range(24):
        controller.strategy.observe(s, (), True)
    assert controller.strategy.target is None
    failures = controller.memory.experience.failures(controller.route.now)
    assert len(failures) == 1
    assert failures[0]['reobserve_version'] == 1


def test_legacy_premature_failure_reopens_without_erasing_history(controller):
    s, terrain, obj, target = remembered(controller)
    experience = controller.memory.experience
    experience.fail(controller.route.now, target, 'Last-seen person was not found at the observed location')
    import json
    row = experience.db.execute('SELECT scope,target,payload FROM agent_attempts WHERE run_id=?',
                                (experience.run_id,)).fetchone()
    payload = json.loads(row[2])
    payload.pop('reobserve_version')
    experience.db.execute('UPDATE agent_attempts SET payload=? WHERE run_id=? AND scope=? AND target=?',
                          (json.dumps(payload), experience.run_id, row[0], row[1]))
    experience.db.commit()
    assert not experience.failures(controller.route.now)
    assert experience.recent(1)[0]['kind'] == 'attempt_failed'


def test_exhausted_viewpoint_preserves_other_approaches_for_model(controller):
    from jpp.agent.navigation_trace import record_target
    s, terrain, obj, target = remembered(controller)
    record_target(controller.memory, target)
    record_target(controller.memory, target)
    available = candidates(s, controller.memory, terrain)
    alternative = next(t for t in available if t['id'] == obj['id'])
    assert alternative['cell'] != target['cell']
    assert alternative['reobserve_interaction']


def test_failed_recheck_does_not_blacklist_person_or_forget_prior_approaches(controller):
    s, terrain, obj, target = remembered(controller)
    experience = controller.memory.experience
    reason = 'Last-seen person was not found at the observed location'
    experience.fail(controller.route.now, target, reason)
    alternative = next(t for t in candidates(s, controller.memory, terrain,
        excluded={obj['id']}) if t['id'] == obj['id'])
    assert alternative['cell'] != target['cell']
    experience.fail(controller.route.now, alternative, reason)
    assert len(experience.failures(controller.route.now)) == 2
    remaining = candidates(s, controller.memory, terrain)
    assert all(t['cell'] not in (target['cell'], alternative['cell'])
               for t in remaining if t['id'] == obj['id'])


def test_goal_lead_reconsideration_preserves_shared_model_choice(controller):
    from types import SimpleNamespace
    s, terrain, obj, target = remembered(controller)
    controller.strategy.provider = SimpleNamespace(shared_control=True)
    controller.strategy.data['enabled'] = True
    obj['visible'] = True
    s.x, s.y = 2, 1
    controller.strategy.target = {'id':'explore:far', 'kind':'explore', 'cell':[5,5],
                                 'map':'09:02', 'direction':''}
    controller.strategy.reconsider_interaction(s, terrain, set())
    assert controller.strategy.target is None
