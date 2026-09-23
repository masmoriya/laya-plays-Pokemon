"""Real pinned map routes and incidental-dialogue regressions."""
from types import SimpleNamespace as NS

from jpp.agent.travel_atlas import atlas, atlas_exits, itinerary, rank_travel, travel_context
from jpp.agent.journey_context import objective_clues
from jpp.agent.local_planner_context import planner_context
from jpp.route_progress import MAIN
from jpp.gold97_collision import Gold97CollisionMap


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


def test_collision_verified_warp_tile_exposes_pinned_destination_before_live_exit():
    s = state(map_group=0x13, map_number=0x09, x=13, y=4, map_width=20, map_height=36)
    tiles = bytearray([0]) * (20 * 36)
    tiles[5 * 20 + 13] = 0x70
    terrain = Gold97CollisionMap((0x13, 0x09), 20, 36, bytes(tiles))
    targets = atlas_exits(s, {(13, 5): 'down'}, (), terrain)
    assert any(t['destination_key'] == '13:0D' for t in targets)


def test_forward_mapped_boundary_is_available_as_a_verifiable_exit():
    s = state(map_group=9, map_number=10, x=1, y=1,
              map_width=10, map_height=8)
    terrain = Gold97CollisionMap((9, 10), 10, 8, bytes(80))
    targets = atlas_exits(s, {(0, 7): 'left'}, (), terrain,
                          required_destination='0A:01')
    forward = next(t for t in targets if t['destination_key'] == '0A:01')
    assert forward['cell'] == [0, 7]
    assert forward['direction'] == 'left'
    assert 'confirm by observing arrival' in forward['destination_evidence']


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


def test_later_goal_explores_toward_its_next_exit_when_gate_is_not_reachable():
    from jpp.agent.travel_atlas import rank_travel_frontier
    s = state(map_group=2, map_number=3, x=12, y=14, map_width=20, map_height=18)
    targets = [{'id': 'farther', 'kind': 'explore', 'cell': [15, 14]},
               {'id': 'toward-route118', 'kind': 'explore', 'cell': [8, 14]}]
    result = rank_travel_frontier(targets, s, 22, 100)
    assert result[0]['id'] == 'toward-route118'
    assert result[0]['travel_route'] and result[0]['journey_reward'] == 200


def test_live_collision_snapshot_has_the_frontier_field_used_by_candidate_ranking():
    from jpp.gold97_collision import Gold97CollisionMap
    from jpp.agent.travel_atlas import rank_collision_frontier
    terrain = Gold97CollisionMap((2, 3), 20, 18, bytes(20 * 18))
    s = state(map_group=2, map_number=3, x=12, y=14,
              map_width=20, map_height=18)
    targets = [{'id': 'away', 'kind': 'explore', 'cell': [15, 14]},
               {'id': 'toward-route118', 'kind': 'explore', 'cell': [8, 14]}]
    result = rank_collision_frontier(targets, s, 22, 100, None, terrain)
    assert result[0]['id'] == 'toward-route118'
    assert result[0]['travel_route']
    # Production terrain intentionally has no old ``seen`` attribute.
    assert not hasattr(terrain, 'seen')


def test_incidental_reobservation_does_not_hide_the_next_route_frontier():
    from jpp.agent.travel_atlas import rank_travel_frontier
    s = state(map_group=2, map_number=3, x=12, y=14,
              map_width=20, map_height=18)
    targets = [{'id': 'last-seen-person', 'kind': 'explore', 'cell': [13, 9],
                'reobserve_interaction': True, 'journey_reward': 60},
               {'id': 'toward-route118', 'kind': 'explore', 'cell': [7, 14],
                'journey_reward': 2}]
    result = rank_travel_frontier(targets, s, 22, 100)
    assert result[0]['id'] == 'toward-route118'
    assert result[0]['travel_route'] and result[0]['journey_reward'] == 200


def test_named_town_is_not_treated_as_an_interaction_objective_during_travel():
    from jpp.agent.journey_guidance import rank_candidates
    person = {'id': 'town-person', 'kind': 'talk', 'label': 'Talk to an unvisited sprite',
              'category': 'npc'}
    traveling = rank_candidates([person], MAIN[22], current_area='Sanskrit Town',
                                traveling=True)[0]
    participant = {**person, 'goal_interaction': True}
    visiting = rank_candidates([participant], MAIN[22], current_area='Sanskrit Town',
                               traveling=True)[0]
    assert not traveling['goal_interaction']
    assert visiting['goal_interaction']


def test_later_journey_uses_known_route_instead_of_optional_cave():
    s = state(map_group=2, map_number=5)
    context = travel_context(s, 22)
    assert context['next_map'] == '02:03'
    targets = [{'id': 'cave', 'kind': 'exit', 'destination_key': '03:2B', 'journey_reward': 25},
               {'id': 'west', 'kind': 'exit', 'destination_key': '02:03', 'journey_reward': 25}]
    ranked = rank_travel(targets, s, 22, 100)
    assert ranked[0]['id'] == 'west' and ranked[0]['travel_route']


def test_multi_stop_goal_routes_to_its_final_named_destination():
    context = travel_context(state(map_group=2, map_number=8), 22)
    assert context['destination'] == 'Sunpoint City'
    assert context['route'][-1]['map'] == '13:01'


def test_sunpoint_docks_is_the_forward_goal_after_reaching_sunpoint_city():
    context = travel_context(state(map_group=0x13, map_number=1), 23)
    assert context['destination'] == 'Sunpoint Docks Sunpoint Gate'
    assert context['next_map'] == '13:0A'
    assert context['route'][-1]['map'] == '13:0A'


def test_board_ship_routes_from_sunpoint_docks_to_rocket_ship_base():
    context = travel_context(state(map_group=0x13, map_number=0x09), 24)
    assert context['destination'] == 'Rocket Ship Base'
    assert context['next_map'] == '13:0D'
    assert context['route'][-1]['map'] == '13:0D'


def test_sunpoint_city_and_docks_complete_as_distinct_journey_stages():
    from jpp.route_progress import RouteProgress
    route = RouteProgress(completed=set(range(1, 22)) | {23})
    city = state(map_group=0x13, map_number=1, area_name='Sunpoint City')
    route.observe(city)
    assert 22 in route.completed and 23 not in route.completed
    assert route.now == 23
    docks = state(map_group=0x13, map_number=0x0A, area_name='Sunpoint Docks')
    route.observe(docks)
    assert route.now == 24


def test_board_ship_completes_on_confirmed_ship_map_arrival():
    from jpp.route_progress import RouteProgress
    route = RouteProgress(completed=set(range(1, 24)))
    ship = state(map_group=0x13, map_number=0x0D, area_name='Rocket Ship Base')
    route.observe(ship)
    assert 24 in route.completed
    assert route.now == 25


def test_configured_itinerary_keeps_multi_stop_goal_from_routing_back_to_named_town():
    from jpp.agent.journey_routes import rank_known_routes
    from jpp.agent.travel_atlas import rank_travel_frontier
    s = state(map_group=2, map_number=8, x=69, y=6, map_width=70, map_height=18)
    itinerary = travel_context(s, 22)
    assert itinerary['next_map'] == '02:09'
    targets = [
        {'id': 'return-sanskrit', 'kind': 'exit', 'cell': [69, 10],
         'destination_key': '02:03', 'journey_reward': 0},
        {'id': 'forward-frontier', 'kind': 'explore', 'cell': [60, 6],
         'journey_reward': 0},
    ]
    # The previously observed map graph points toward Sanskrit Town because
    # it is mentioned in the same milestone. The pinned itinerary must win.
    ranked = rank_known_routes(targets, s, None, MAIN[22], 100,
                               required_next_map=itinerary['next_map'])
    assert not ranked[0].get('goal_route')
    ranked = rank_travel_frontier(ranked, s, 22, 100)
    assert ranked[0]['id'] == 'forward-frontier'
    assert ranked[0]['travel_route']


def test_route_waypoint_crosses_a_large_observed_map_toward_its_actual_next_gate():
    from jpp.agent.travel_atlas import next_route_waypoint
    s = state(map_group=2, map_number=8, x=69, y=6, map_width=70, map_height=18)

    class Memory:
        def map(self, key):
            return {'visited': [[69, 6]]}

    reachable = NS(distances={(68, 6): 1, (62, 6): 7, (60, 6): 9})
    waypoint = next_route_waypoint(reachable, s, Memory(), None,
                                   '02:09', 100, ())
    assert waypoint['cell'] == [60, 6]
    assert waypoint['travel_route']
    assert waypoint['route_destination'] == '02:09'


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
    preferred = preferred_targets(ranked)
    assert {t['id'] for t in preferred} == {'west'}
    assert preferred[0]['travel_route']
    # Arrival information expires when a verified objective advances.
    later = [{k: v for k, v in tasks[0].items() if k != 'recent_return'}]
    assert not mark_entry_returns(later, memory, s, 23)[0].get('recent_return')
