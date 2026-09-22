"""A completed arrival must not drop the remaining objective in that city."""
from types import SimpleNamespace as NS
import pytest

from jpp.agent.journey_guidance import rank_candidates
from jpp.agent.journey_routes import rank_known_routes
from jpp.route_progress import MAIN


def exit_to(key, name):
    return {'id': key, 'kind': 'exit', 'destination_key': key,
            'destination': name, 'label': 'Continue to ' + name}


def test_port_and_radio_novelty_do_not_match_missing_child_goal():
    tasks = rank_candidates([exit_to('04:08', 'Teknos Port Passage'),
                             exit_to('0A:12', 'Radio Tower 1F'),
                             {'id': 'npc', 'kind': 'talk', 'label': 'Talk to a local sprite'}],
                            MAIN[12], current_area='Teknos City')
    assert tasks[0]['id'] == 'npc'
    assert all(t['journey_reward'] == 0 for t in tasks[1:])


def test_radio_tower_returns_to_teknos_after_arrival_is_complete():
    memory = NS(world={'route': {'completed': list(range(1, 12))},
                       'journey_strategy': {'connections': [], 'map_exits': {
                           '0A:15': ['0A:14', '0A:16'], '0A:14': ['0A:13'],
                           '0A:13': ['0A:12'], '0A:12': ['0A:01'],
                           '0A:01': ['0A:19'], '0A:19': ['0E:01'],
                           '0E:01': ['0A:19'], '0E:02': ['04:08'],
                           '04:08': ['04:05'], '04:05': ['04:08']}}})
    state = NS(map_group=10, map_number=21, mechanics_verified=True)
    tasks = rank_candidates([exit_to('0A:14', 'Radio Tower 3F'),
                             exit_to('0A:16', 'Radio Tower 5F'),
                             {'id': 'npc', 'kind': 'talk', 'label': 'Talk to a sprite'}],
                            MAIN[12], current_area='Radio Tower 4F')
    result = rank_known_routes(tasks, state, memory, MAIN[12], 100)
    assert result[0]['destination_key'] == '0A:14'
    assert result[0]['goal_route']


def test_teknos_port_is_not_equivalent_to_teknos_city():
    memory = NS(world={'route': {'completed': list(range(1, 12))},
                       'journey_strategy': {'connections': [], 'map_exits': {
                           '0E:02': ['04:08', '0E:01'], '04:08': ['04:05'],
                           '04:05': ['04:08'], '0E:01': ['0A:19']}}})
    state = NS(map_group=14, map_number=2, mechanics_verified=True)
    tasks = rank_candidates([exit_to('04:08', 'Teknos Port Passage'),
                             exit_to('0E:01', 'Westport Port')], MAIN[12])
    result = rank_known_routes(tasks, state, memory, MAIN[12], 100)
    assert result[0]['destination_key'] == '04:08'
    assert result[0]['goal_route']


def test_teknos_exit_does_not_invent_an_unobserved_mine_connection():
    memory = NS(world={'route': {'completed': list(range(1, 12))},
                       'journey_strategy': {'connections': [], 'map_exits': {
                           '04:05': ['04:07', '04:08'], '04:08': ['04:05', '0E:02']}}})
    state = NS(map_group=4, map_number=5, mechanics_verified=True)
    tasks = rank_candidates([exit_to('04:07', 'Route 120'),
                             exit_to('04:08', 'Teknos Port Passage'),
                             {'id': 'npc', 'kind': 'talk', 'label': 'Talk to a local sprite'}],
                            MAIN[12], current_area='Teknos City')
    result = rank_known_routes(tasks, state, memory, MAIN[12], 100)
    assert not any(t.get('goal_route') for t in result)
    assert result[0]['kind'] == 'talk'
    state.mechanics_verified = False
    assert not any(t.get('goal_route') for t in rank_known_routes(
        rank_candidates([exit_to('04:07', 'Route 120')], MAIN[12]),
        state, memory, MAIN[12], 100))


def test_aquarium_upper_floor_keeps_the_objective_reward():
    tasks = rank_candidates([exit_to('04:05', 'Teknos City'),
                             exit_to('04:0B', 'Teknos Aquarium 2F')],
                            MAIN[14], current_area='Teknos Aquarium 1F')
    assert tasks[0]['destination_key'] == '04:0B'
    assert tasks[0]['goal_destination'] and tasks[0]['within_goal']
    assert tasks[0]['journey_reward'] > tasks[1]['journey_reward']


def test_aquarium_rocket_interactions_outrank_retracing_stairs():
    tasks = rank_candidates([exit_to('04:0A', 'Teknos Aquarium 1F'),
                             {'id': 'rocket', 'kind': 'talk', 'label': 'Talk to an unvisited sprite'}],
                            MAIN[14], current_area='Teknos Aquarium 2F')
    assert tasks[0]['id'] == 'rocket' and tasks[0]['goal_interaction']
    assert tasks[0]['journey_reward'] > tasks[1]['journey_reward']


def test_observed_route_toward_aquarium_outranks_incidental_departure():
    memory = NS(world={'route': {'completed': list(range(1, 14))},
                       'journey_strategy': {'connections': [], 'map_exits': {
                           '04:07': ['04:05', '04:06'], '04:05': ['04:0A'],
                           '04:0A': ['04:0B']}}})
    s = NS(map_group=4, map_number=7, mechanics_verified=True)
    tasks = rank_candidates([exit_to('04:06', 'Route 119'),
                             exit_to('04:05', 'Teknos City')], MAIN[14])
    result = rank_known_routes(tasks, s, memory, MAIN[14], 100)
    assert result[0]['destination_key'] == '04:05' and result[0]['goal_route']


@pytest.mark.parametrize(('map_number', 'area', 'keeps_entry_bonus'), [
    (11, 'Teknos Aquarium 2F', False),
    (5, 'Teknos City', True),
])
def test_visited_objective_floor_only_loses_entry_bonus_while_inside(
        tmp_path, map_number, area, keeps_entry_bonus):
    from jpp.agent.gold97_controller import Gold97Controller
    from jpp.agent.journey_targets import candidates
    from jpp.gold97_collision import Gold97CollisionMap
    from jpp.route_progress import RouteProgress
    owner = Gold97Controller('aquarium', database=tmp_path/'memory.sqlite', vision_enabled=False)
    try:
        owner.route = RouteProgress(set(range(1, 14)))
        owner.memory.world['route'] = owner.route.to_dict()
        owner.strategy.data['route_maps']['14'] = ['04:05', '04:0A', '04:0B']
        s = NS(map_group=4, map_number=map_number, map_width=16, map_height=8,
               x=5, y=5, area_name=area, in_battle=False, party=(), badge_ids=(),
               map_exits=((5, 7, 'down', 4, 10),))
        terrain = Gold97CollisionMap((4, map_number), 16, 8, bytes(128))
        tasks = candidates(s, owner.memory, terrain)
        exit = next(t for t in tasks if t.get('destination_key') == '04:0A')
        assert (exit['journey_reward'] >= 100) is keeps_entry_bonus
    finally:
        owner.close()
