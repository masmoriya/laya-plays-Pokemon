"""Real pinned map routes and incidental-dialogue regressions."""
from types import SimpleNamespace as NS

from jpp.agent.travel_atlas import atlas, atlas_exits, itinerary, rank_travel, travel_context
from jpp.agent.journey_context import objective_clues
from jpp.agent.local_planner_context import planner_context
from jpp.route_progress import MAIN


def state(**changes):
    return NS(**({'map_group': 4, 'map_number': 5, 'mechanics_verified': True,
                 'route_103_slowpoke_cleared': True, 'x': 23, 'y': 13,
                 'map_width': 50, 'map_height': 40, 'map_exits': ()} | changes))


def test_birdon_route_uses_return_ferry_and_route103():
    assert itinerary(state(), '08:05') == [
        '04:05', '04:08', '0E:02', '0E:01', '0A:19', '0A:01', '09:08', '08:04', '08:05']
    assert travel_context(state(), 16)['next_map'] == '04:08'
    assert itinerary(state(), '03:10')[-2:] == ['08:05', '03:10']


def test_unknown_build_and_slowpoke_gate_do_not_claim_a_route():
    assert itinerary(state(mechanics_verified=False), '08:05') == []
    assert travel_context(state(route_103_slowpoke_cleared=False), 16)['route'] == []


def test_ferry_boarding_is_reachable_script_target():
    s = state(map_group=14, map_number=2)
    target = atlas_exits(s, {(3, 9): 'down'}, ())[0]
    assert target['destination_key'] == '0E:01'
    assert target['cell'] == [3, 9]
    assert not atlas_exits(s, {(4, 9): 'left'}, ())
    assert not atlas_exits(s, {(3, 9): 'down'}, {target['id']})


def test_observed_unknown_door_gets_atlas_destination():
    edge = next(e for e in atlas()['edges']['04:05'] if e['to'] == '04:08')
    cell = tuple(edge['cell'])
    s = state(map_exits=((*cell, '', 0, 0),))
    assert atlas_exits(s, {cell: 'down'}, ())[0]['destination_key'] == '04:08'
    assert not atlas_exits(state(), {cell: 'down'}, ())


def test_route_beats_casual_npc_and_survives_qwen_compaction():
    targets = [{'id': 'npc', 'kind': 'talk', 'journey_reward': 60},
               {'id': 'port', 'kind': 'exit', 'destination_key': '04:08', 'journey_reward': 0}]
    ranked = rank_travel(targets, state(), 16, 100)
    assert ranked[0]['id'] == 'port'
    context = planner_context({'candidates': ranked, 'travel': travel_context(state(), 16)})
    assert context['travel']['next_map'] == '04:08'
    assert context['travel']['route'][-1]['name'] == 'Birdon Town'


def test_incidental_dialogue_is_not_objective_evidence():
    chatter = {'id': 'clue:1', 'text': 'than when I was young!'}
    lead = {'id': 'clue:2', 'text': 'The Slowpoke are in trouble at Birdon.'}
    assert objective_clues([chatter, lead], MAIN[16]) == [lead]


def test_completed_oak_call_advances_from_actual_cartridge_flag():
    from jpp.gold97_story import story_milestones
    from jpp.route_progress import RouteProgress
    memory = bytearray(65536)
    route = RouteProgress(set(range(1, 16)))
    s = state(area_name='Teknos City', badge_ids=(1, 2, 3))
    s.story_milestones = story_milestones(memory, True)
    route.observe(s)
    assert route.now == 16
    memory[0xDA72 + 73 // 8] |= 1 << (73 % 8)
    assert 16 not in story_milestones(memory, False)
    s.story_milestones = story_milestones(memory, True)
    route.observe(s)
    assert route.now == 17
    s.area_name = 'Birdon Town'
    route.observe(s)
    assert route.now == 18
    s.area_name = 'Slowpoke Well B1F'
    route.observe(s)
    assert route.now == 19


def test_passage_stairs_and_unseen_exit_approach_keep_travel_priority():
    from jpp.agent.travel_atlas import rank_travel_frontier
    s = state(map_number=8)
    stairs = {'kind': 'exit', 'destination_key': '04:08'}
    assert rank_travel([stairs], s, 17, 100)[0]['travel_route']
    s = state(map_group=14, map_number=2, x=7, y=5)
    targets = [{'kind': 'explore', 'cell': [4, 8]},
               {'kind': 'explore', 'cell': [9, 4]}]
    result = rank_travel_frontier(targets, s, 17, 100)
    assert result[0]['cell'] == [4, 8]
    assert result[0]['travel_route']


def test_later_journey_uses_known_route_instead_of_optional_cave():
    s = state(map_group=2, map_number=5)
    context = travel_context(s, 22)
    assert context['next_map'] == '02:03'
    targets = [{'id': 'cave', 'kind': 'exit', 'destination_key': '03:2B', 'journey_reward': 25},
               {'id': 'west', 'kind': 'exit', 'destination_key': '02:03', 'journey_reward': 25}]
    ranked = rank_travel(targets, s, 22, 100)
    assert ranked[0]['id'] == 'west' and ranked[0]['travel_route']


def test_passage_explores_instead_of_returning_through_entry():
    from jpp.agent.passage_navigation import mark_entry_returns
    from jpp.agent.travel_atlas import rank_travel_frontier
    from jpp.agent.navigation_policy import preferred_targets
    s = state(map_group=3, map_number=43, x=56, y=15, map_width=60, map_height=20)
    memory = NS(world={'navigation_arrival': {
        'map': '03:2B', 'from': '02:05', 'cell': [56, 15], 'goal': 22}})
    tasks = [{'id': 'entry', 'kind': 'exit', 'cell': [56,15], 'destination_key': '02:05'},
             {'id': 'west', 'kind': 'explore', 'cell': [50,12]},
             {'id': 'east', 'kind': 'explore', 'cell': [58,12]}]
    mark_entry_returns(tasks, memory, s, 22)
    ranked = rank_travel(tasks, s, 22, 100, memory)
    assert tasks[0]['recent_return'] and not tasks[0].get('travel_route')
    ranked = rank_travel_frontier(ranked, s, 22, 100, memory)
    assert {t['id'] for t in preferred_targets(ranked)} == {'west', 'east'}
    # Arrival information expires when a verified objective advances.
    later = [{k: v for k, v in tasks[0].items() if k != 'recent_return'}]
    assert not mark_entry_returns(later, memory, s, 23)[0].get('recent_return')
