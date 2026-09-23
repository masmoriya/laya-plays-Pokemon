"""Surf becomes a route action only when collision and HM facts prove it is needed."""
from types import SimpleNamespace as NS

from jpp.agent.field_actions import FieldAction
from jpp.agent.discovery import DisplayMemory, observe_terrain
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.navigation_paths import paths
from jpp.agent.surf_navigation import surf_exit_candidate
from jpp.gold97_collision import Gold97CollisionMap


def state(x=0, y=1, moves=('Surf',)):
    return NS(map_group=2, map_number=8, x=x, y=y, map_width=5, map_height=3,
              mechanics_verified=True, badge_ids=('johto_1', 'johto_2', 'johto_3', 'johto_4'),
              party=[NS(moves=list(moves))], owned_hms=('Surf',),
              map_exits=((4, 1, '', 2, 9),), player_facing='right',
              strength_active=False, received_cut_from_bill=False)


def terrain():
    return Gold97CollisionMap((2, 8), 5, 3,
                              bytes((7, 7, 7, 7, 7,
                                     0, 32, 32, 32, 0,
                                     7, 7, 7, 7, 7)))


def test_surf_exit_uses_reachable_shore_and_observed_water_crossing(tmp_path):
    memory = Gold97Memory('surf-test', database=tmp_path / 'memory.sqlite')
    s, ground = state(), terrain()
    land = paths(s, memory, ground)
    target = surf_exit_candidate(s, memory, ground, land, '02:09', 100)
    assert target['kind'] == 'exit'
    assert target['surf_activation'] and target['travel_route']
    assert target['cell'] == [0, 1] and target['direction'] == 'right'
    assert target['target_cell'] == [4, 1]
    memory.close()


def test_atlas_gate_can_trigger_surf_before_the_warp_enters_live_exit_table(tmp_path):
    memory = Gold97Memory('surf-atlas-test', database=tmp_path / 'memory.sqlite')
    width, height = 70, 18
    tiles = bytearray([7]) * (width * height)
    for x in range(4, 70):
        tiles[11 * width + x] = 0
    for x in range(30, 36):
        tiles[11 * width + x] = 32
    s = state(x=69, y=11)
    s.map_width, s.map_height = width, height
    s.map_exits = ((69, 10, 'right', 2, 3),)  # only the known return gate is exposed
    ground = Gold97CollisionMap((2, 8), width, height, bytes(tiles))
    land = paths(s, memory, ground)
    assert (4, 11) not in land
    target = surf_exit_candidate(s, memory, ground, land, '02:09', 100)
    assert target['target_cell'] == [4, 11]
    assert target['cell'] == [36, 11]
    assert target['direction'] == 'left'
    memory.close()


def test_surf_search_uses_collision_verified_water_hidden_from_exploration_memory(tmp_path):
    memory = Gold97Memory('surf-hidden-crossing', database=tmp_path / 'memory.sqlite')
    width, height = 70, 18
    tiles = bytearray([7]) * (width * height)
    for x in range(4, 70):
        tiles[11 * width + x] = 0
    for y in range(8, 11):
        for x in range(58, 70):
            tiles[y * width + x] = 0
    for x in range(58, 65):
        tiles[10 * width + x] = 0
    for x in range(30, 36):
        tiles[11 * width + x] = 32
    s = state(x=64, y=9)
    s.map_width, s.map_height = width, height
    s.map_exits = ((69, 10, 'right', 2, 3),)
    visible = tuple((x, 11) for x in range(36, 70)) + tuple(
        (x, y) for x in range(58, 70) for y in range(8, 11))
    raw = Gold97CollisionMap((2, 8), width, height, bytes(tiles), visible_cells=visible)
    observed = observe_terrain(memory, s, raw, True)
    land = paths(s, memory, observed)
    assert (4, 11) not in land
    target = surf_exit_candidate(s, memory, observed, land, '02:09', 100)
    assert target['target_cell'] == [4, 11]
    assert tuple(target['cell']) in land
    memory.close()


def test_water_path_is_available_only_after_player_is_observed_on_water(tmp_path):
    memory = Gold97Memory('surf-path', database=tmp_path / 'memory.sqlite')
    ground = terrain()
    assert (4, 1) not in paths(state(), memory, ground)
    crossing = paths(state(x=1), memory, ground)
    assert crossing.get((4, 1)) == 'right'
    memory.close()


def test_field_action_can_select_the_required_surf_move(tmp_path):
    memory = Gold97Memory('surf-action', database=tmp_path / 'memory.sqlite')
    s = state()
    npc = {'id': 'surf:02:08:4:1:02:09', 'map': '02:08', 'cell': [0, 1],
           'pages': ['Verified water route'], 'category': 'obstacle',
           'status': 'pending', 'outcome': 'unresolved'}
    action = FieldAction()
    assert action.start(s, npc, memory, preferred_move='SURF', direction='right')
    assert action.move == 'SURF' and action.slot == 0 and action.direction == 'right'
    memory.close()
