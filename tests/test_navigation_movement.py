"""Arrival timing and truthful exit candidates prevent reversal loops."""
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.journey_exits import exit_candidates
from jpp.agent.journey_targets import paths
from jpp.agent.route_execution import committed_heading
from jpp.gold97_collision import Gold97CollisionMap
from jpp.gold97_movement import player_destination


@pytest.fixture
def owner(tmp_path):
    controller = Gold97Controller('movement', database=tmp_path/'memory.sqlite',
                                  vision_enabled=False)
    yield controller
    controller.close()


def state(**changes):
    return NS(**(dict(map_group=4, map_number=7, map_width=8, map_height=8,
                     x=3, y=3, in_battle=False, player_moving=False,
                     map_exits=()) | changes))


def commit(owner, cell):
    owner.terrain = Gold97CollisionMap((4, 7), 8, 8, bytes(64))
    owner.strategy.target = dict(id='route', kind='explore', cell=list(cell),
                                 map='04:07', direction='', label='Explore')


def test_hold_releases_before_inflight_arrival(owner):
    commit(owner, (3, 2))
    assert not committed_heading(owner, state(player_moving=True,
                                 player_next_position=(3, 2)), 'up')


def test_hold_releases_before_inflight_turn(owner):
    commit(owner, (4, 2))
    # From the current coordinate UP is correct; after this step RIGHT is.
    assert not committed_heading(owner, state(player_moving=True,
                                 player_next_position=(3, 2)), 'up')


def test_straight_continuation_remains_held(owner):
    commit(owner, (3, 0))
    assert committed_heading(owner, state(player_moving=True,
                              player_next_position=(3, 2)), 'up')


def test_unknown_animation_destination_releases_safely(owner):
    commit(owner, (3, 0))
    assert not committed_heading(owner, state(player_moving=True), 'up')


@pytest.mark.parametrize(('origin', 'destination', 'expected'), [
    ((3, 3), (3, 2), (3, 2)),
    ((3, 3), (3, 3), None),
    ((3, 3), (3, 1), None),
    ((0, 3), (-1, 3), None),
    ((7, 3), (8, 3), None),
])
def test_native_destination_accepts_only_adjacent_in_bounds_tiles(origin, destination, expected):
    memory = bytearray(65536)
    memory[0xD4E6:0xD4EA] = bytes(v + 4 for point in (destination, origin) for v in point)
    assert player_destination(memory, 8, 8) == expected


def test_interior_arrival_cannot_invent_a_return_door(owner):
    s = state()
    commit(owner, (4, 2))
    owner.strategy.data['connections'] = [dict(
        **{'from': '03:0D', 'to': '04:07'}, at=[0, 1], arrival=[3, 3], direction='up')]
    assert not exit_candidates(s, owner.memory, paths(s, owner.memory, owner.terrain), (), owner.terrain)


def test_current_geometry_owns_an_exit_despite_stale_heading(owner):
    s = state(map_exits=((3, 2, '', 0, 0),))
    commit(owner, (4, 2))
    owner.strategy.data['connections'] = [dict(
        **{'from': '04:07', 'to': '03:0D'}, at=[3, 2], arrival=[0, 1], direction='down')]
    targets = exit_candidates(s, owner.memory, paths(s, owner.memory, owner.terrain), (), owner.terrain)
    assert len(targets) == 1
    assert targets[0]['id'].startswith('geometry:') and targets[0]['direction'] == ''


def test_boundary_return_uses_boundary_direction(owner):
    s = state()
    commit(owner, (4, 2))
    owner.strategy.data['connections'] = [dict(
        **{'from': '03:0D', 'to': '04:07'}, at=[0, 1], arrival=[7, 3], direction='up')]
    targets = exit_candidates(s, owner.memory, paths(s, owner.memory, owner.terrain), (), owner.terrain)
    assert len(targets) == 1 and targets[0]['direction'] == 'right'


def test_observed_floor_rejects_a_corrupt_historical_exit(owner):
    from jpp.agent.discovery import ObservedTerrain
    s = state()
    terrain = ObservedTerrain((4, 7), 8, 8, bytes(64), seen=frozenset({(3, 2)}))
    owner.strategy.data['connections'] = [dict(
        **{'from': '04:07', 'to': '04:04'}, at=[3, 2], arrival=[4, 7], direction='down')]
    assert not exit_candidates(s, owner.memory, {(3, 2): 'up'}, (), terrain)


def test_unknown_boundary_remembers_outward_heading_not_approach(owner):
    s = state(x=7, y=3, map_exits=((7, 3, 'right', 0, 0),),
              screen_lines=(), party=())
    observation = owner.strategy.observations
    observation.observe(s, (), overworld=True, milestone=14)
    observation.last_direction = 'up'
    observation.observe(state(map_number=5, x=0, screen_lines=(), party=()), (),
                        overworld=True, milestone=14)
    assert owner.strategy.data['connections'][-1]['direction'] == 'right'


def test_discovery_does_not_label_portal_with_incompatible_old_transition(owner):
    from dataclasses import replace
    from jpp.agent.discovery import observe_terrain
    s = state(map_exits=((3, 2, '', 4, 5),))
    commit(owner, (4, 2))
    owner.strategy.data['connections'] = [dict(
        **{'from': '04:07', 'to': '04:04'}, at=[3, 2], arrival=[4, 7], direction='down')]
    observed = observe_terrain(owner.memory, s,
                               replace(owner.terrain, visible_cells=((3, 2),)), True)
    assert observed.exits == ((3, 2, '', 0, 0),)


@pytest.mark.parametrize('discovery', [False, True])
def test_waypoint_arrival_only_resets_loop_history_after_new_evidence(owner, discovery):
    s = state(screen_lines=(), party=())
    owner.strategy.observe(s, (), True)
    commit(owner, (3, 2))
    owner.strategy.chosen('up')
    owner.movement_history.observe('04:07', (3, 3))
    if discovery:
        owner.memory.world['discovery_revision'] = 1
    owner.strategy.observe(state(y=2, screen_lines=(), party=()), (), True)
    assert bool(owner.movement_history.points) is not discovery
    event = owner.strategy.data['events'][-1]
    assert event['kind'] == ('subgoal_completed' if discovery else 'exploration_reached')
