"""Door boundaries, shared corridors, and the planner-to-executor handoff."""
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.journey_targets import candidates, paths
from jpp.agent.local_planner_context import planner_context
from jpp.agent.local_vision import LocalJourneyProvider
from jpp.agent.navigation_memory import navigation_memory
from jpp.gold97_collision import Gold97CollisionMap


@pytest.fixture
def owner(tmp_path):
    controller = Gold97Controller('doors', database=tmp_path / 'agent.sqlite',
                                 vision_enabled=False)
    yield controller
    controller.close()


def state(**changes):
    return NS(**(dict(map_group=3, map_number=13, x=4, y=1,
                     map_width=9, map_height=9, map_exits=(),
                     mechanics_verified=False, area_name='Boulder Mines 1F',
                     party=(), badge_ids=(), in_battle=False) | changes))


def corridor():
    cells = bytearray([7] * 81)
    for x, y in [(4, y) for y in range(1, 6)] + [(x, 5) for x in range(1, 8)]:
        cells[y * 9 + x] = 0
    return Gold97CollisionMap((3, 13), 9, 9, bytes(cells))


def test_branches_sharing_first_step_remain_exploration_choices(owner):
    s, terrain = state(), corridor()
    reachable = paths(s, owner.memory, terrain)
    assert reachable[(1, 5)] == reachable[(7, 5)] == 'down'
    choices = [t for t in candidates(s, owner.memory, terrain) if t['kind'] == 'explore']
    assert any(t['cell'][0] < s.x for t in choices)
    assert any(t['cell'][0] > s.x for t in choices)


def test_raw_cartridge_door_is_never_an_exploration_target(owner):
    s = state(map_exits=((4, 5, '', 3, 14),))
    choices = candidates(s, owner.memory, corridor())
    assert any(t['kind'] == 'exit' and t['cell'] == [4, 5] for t in choices)
    assert not any(t['kind'] == 'explore' and t['cell'] == [4, 5] for t in choices)


def test_exit_activation_survives_planner_and_tactical_context(owner):
    target = dict(id='door', kind='exit', map='03:0D', cell=[4, 5],
                  direction='down', reentry=[4, 4], destination_key='03:0E')
    packed = planner_context({'candidates': [target]})['candidates'][0]
    assert packed['direction'] == 'down'
    assert packed['reentry'] == [4, 4]
    owner.strategy.target = target
    approach = navigation_memory(owner.strategy, state())['approach']
    assert approach['cell'] == [4, 5] and approach['direction'] == 'down'


def test_pending_planner_keeps_local_options_on_travel_route(owner):
    route = dict(id='route', kind='explore', map='03:0D', cell=[4, 5],
                 direction='', label='Continue route', travel_route=True)
    detour = dict(id='detour', kind='explore', map='03:0D', cell=[5, 1],
                  direction='', label='Unrelated door')
    terrain = Gold97CollisionMap((3, 13), 9, 9, bytes(81))
    options = owner.strategy.local_options(state(), terrain, [detour, route])
    assert options == {'down': 'Continue route'}
    assert owner.strategy.local_targets['down']['id'] == 'route'


def test_single_travel_target_does_not_dispatch_qwen(owner):
    owner.strategy.provider = LocalJourneyProvider()
    owner.route.completed.update(range(1, 17))
    owner.memory.world['route'] = {'completed': list(range(1, 17))}
    s = state(map_group=14, map_number=2, x=3, y=8,
              map_width=10, map_height=12, mechanics_verified=True,
              route_103_slowpoke_cleared=True, area_name='Teknos Port')
    cells = bytearray([7] * 120)
    cells[83] = cells[93] = 0
    terrain = Gold97CollisionMap((14, 2), 10, 12, bytes(cells))
    options = owner.strategy.plan_next(s, terrain, set())
    assert set(options) == {'down'}
    assert owner.strategy.future is None
    owner.strategy.position = [3, 8]
    owner.strategy.chosen('down')
    assert owner.strategy.target['travel_route']
