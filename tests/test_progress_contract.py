"""General progress rules apply to every map and every owned HM."""
from types import SimpleNamespace as NS
from dataclasses import replace
from test_journey_strategy import controller, state
from test_gold97_roster import mon, state as roster_state
from jpp.agent.exploration_cycles import record_transition, filter_cycles
from jpp.agent.hm_preparation import preparation, rank_preparation
from jpp.agent.gold97_roster import roster_plan
from jpp.agent.local_planner_context import planner_context


def hm_state(**changes):
    base = dict(mechanics_verified=True, owned_hms=('Cut', 'Surf', 'Strength'),
                badge_ids=('johto_1', 'johto_2', 'johto_3'), storage_verified=True,
                party=(mon('leader', moves=('Cut', 'Strength')) ,), box_roster=(),
                map_group=8, map_number=5)
    return NS(**(base | changes))


def test_cave_laps_survive_camera_discovery_dialogue_and_prerequisite_ranking(controller):
    exit = dict(id='arbitrary-cave', map='12:34', kind='exit', cell=[2, 3],
                destination_key='56:78', direction='down', prerequisite=True)
    for turn in range(3):
        controller.memory.world['discovery_revision'] = turn
        controller.strategy.data['clues'].append({'map': '12:34', 'text': f'Unfinished page {turn}'})
        record_transition(controller.memory, '12:34', [2, 3], '56:78')
    assert filter_cycles([exit], controller.memory) == []
    controller.strategy.invalidate()
    assert filter_cycles([exit], controller.memory) == []
    controller.memory.world['field_capabilities'] = ['Surf learned']
    assert filter_cycles([exit], controller.memory) == [exit]


def test_surf_needs_badge_and_compatible_mon_not_another_hm_menu():
    prep = preparation(hm_state(), 21)
    assert prep['action'] == 'badge' and 'Morty' in prep['next']
    assert prep['party_compatible'] == [] and prep['boxed'] == []
    prep = preparation(hm_state(badge_ids=('johto_1','johto_2','johto_3','johto_4')), 22)
    assert prep['action'] == 'catch' and 'unchanged party' in prep['next']


def test_verified_boxed_learner_produces_preserving_transfer():
    swimmer = mon('swimmer', storage_box=2, species_data=NS(field_moves=('Surf',)))
    party = tuple(mon(f'p{i}', level=30-i) for i in range(6))
    party = (replace(party[0], moves=('Cut','Strength')), *party[1:])
    s = hm_state(party=party, box_roster=(swimmer,))
    s.current_box = 0
    assert preparation(s, 21)['action'] == 'withdraw'
    plan = roster_plan(s, required_move='Surf')
    assert plan['kind'] == 'deposit' and plan['identity'] != party[0].identity
    s.party = tuple(m for m in party if m.identity != plan['identity'])
    assert roster_plan(s, required_move='Surf') == {'kind':'withdraw','identity':'swimmer','box':2}
    s.storage_verified = False
    assert preparation(s, 21)['boxed'] == []


def test_planner_keeps_hm_blocker_and_completion_under_pressure():
    progress = {'hm': preparation(hm_state(),21), 'success':'Surf learned and badge earned'}
    packed = planner_context({'progress':progress, 'candidates':[{'id':'gym','kind':'exit'}],
                              'recent':['noise'*200]*20})
    assert packed['progress'] == progress


def test_search_uses_observed_compatible_encounters_and_nearest_center(controller):
    from jpp.agent.hm_preparation import nearest_hops
    s = hm_state(badge_ids=('johto_1','johto_2','johto_3','johto_4'))
    controller.memory.world['hm_encounters'] = {'Surf':[{'species':'eligible swimmer','map':'08:04','cell':[4,5]}]}
    targets = [{'id':'north','kind':'exit','destination_key':'08:04'},
               {'id':'old-cave','kind':'exit','destination_key':'03:11'}]
    ranked = rank_preparation(targets,s,22,100,controller.memory)
    assert ranked[0]['id'] == 'north' and ranked[0]['prerequisite']
    controller.strategy.data['connections'] = [
        {'from':'08:05','to':'08:01'}, {'from':'08:05','to':'08:04'},
        {'from':'08:04','to':'09:02'}, {'from':'09:02','to':'09:07'}]
    assert nearest_hops(controller.memory,'08:05',{'08:01','09:07'}) == {'08:01'}


def test_map_tile_animation_is_not_a_navigation_outcome(controller):
    s = state()
    s.screen_lines = ('BB CCCCC GGGGG',)
    experience = controller.memory.experience
    experience.action(s,'up','Laya',6)
    s.screen_lines = ('MnMnMp BBCC',)
    experience.observe(s,overworld=True)
    assert experience.pending is not None
    s.y += 1
    experience.observe(s,overworld=True)
    assert experience.pending is None
    assert experience.recent(1)[0]['outcome'].startswith('Moved')


def test_prerequisite_waypoints_do_not_get_unlimited_retries(controller):
    from jpp.agent.navigation_trace import record_target, unexhausted
    target = dict(id='search', kind='explore', map='12:34', cell=[2,3], prerequisite=True)
    for index in range(2):
        record_target(controller.memory,target)
        controller.strategy.data['clues'].append({'text':f'Partial sentence {index}','map':'12:34'})
    assert not unexhausted(controller.memory,[target])


def test_unknown_capability_location_does_not_promote_every_viewpoint(controller):
    s = hm_state(badge_ids=('johto_1','johto_2','johto_3','johto_4'))
    targets = [{'id': 'view', 'kind': 'explore', 'cell': [4, 5], 'journey_reward': 2},
               {'id': 'road', 'kind': 'exit', 'destination_key': '12:34', 'journey_reward': 25}]
    ranked = rank_preparation(targets, s, 22, 100, controller.memory)
    assert ranked[0]['id'] == 'road'
    assert not any(t.get('prerequisite') for t in ranked)
