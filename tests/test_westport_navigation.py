"""Westport detours, outward door steps, and goal-specific ferry menus."""

from pathlib import Path

import pytest

from test_journey_strategy import controller, state
from jpp.agent.journey_guidance import rank_candidates
from jpp.agent.journey_targets import candidates, target_options
from jpp.agent.gold97_input import release_restored_buttons
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


def test_department_store_name_does_not_make_it_a_ferry_lead():
    tasks = [dict(id='store', kind='exit', destination='Westport Dept Store 1F',
                  destination_key='0A:06'),
             dict(id='npc', kind='talk', label='Talk to an unvisited sprite')]
    ranked = rank_candidates(tasks, 'Take the Westport Docks ferry to Teknos City after Bugsy',
                             current_area='Westport City')
    assert ranked[0]['id'] == 'npc'
    assert ranked[1]['journey_reward'] == 0
    tasks.append(dict(id='town', kind='exit', destination='Westport City',
                      destination_key='0A:01'))
    assert rank_candidates(tasks, 'Take the Westport Docks ferry to Teknos City after Bugsy',
                           current_area='Westport Dept Store 1F')[0]['id'] == 'town'


@pytest.mark.parametrize('x', [1, 2])
def test_elevator_uses_outward_step_on_either_door(controller, x):
    s = state()
    s.map_group, s.map_number, s.x, s.y = 10, 12, x, 3
    s.map_width, s.map_height = 4, 4
    s.area_name = 'Westport Dept Store Elevator'
    s.map_exits = ((1, 3, '', 10, 6), (2, 3, '', 10, 6))
    controller.strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((10, 12), 4, 4, bytes(16))
    target = next(t for t in candidates(s, controller.memory, terrain) if t['kind'] == 'exit')
    assert target['cell'] == [x, 3]
    assert set(target_options(target, s, controller.memory, terrain)) == {'down'}


@pytest.mark.parametrize('cursor,action', [((1, 6), 'a'), ((1, 8), 'up')])
def test_ferry_menu_is_selected_only_for_verified_ferry_goal(controller, cursor, action):
    s = state()
    s.map_group, s.map_number, s.mechanics_verified = 14, 1, True
    s.screen_lines = ('',) * 6 + ('TEKNOS CITY', '', 'CANCEL')
    s.screen_cursor = cursor
    controller.route = RouteProgress(set(range(1, 11)))
    assert set(controller._options(s, (), False)) == {action}
    s.mechanics_verified = False
    assert set(controller._options(s, (), False)) == {'b'}
    s.mechanics_verified = True
    controller.route = RouteProgress(set(range(1, 12)))
    assert set(controller._options(s, (), False)) == {'b'}


@pytest.mark.parametrize('lines', [('BUY', 'SELL', 'QUIT'), ('HOW MANY?',),
                                 ('A cute DOLL!',), ('That WILL BE 1000.',)])
def test_unplanned_shop_prompts_cancel_even_without_cursor(controller, lines):
    s = state()
    s.screen_lines, s.screen_cursor = lines, None
    assert set(controller._options(s, (), False)) == {'b'}


def test_saved_elevator_checkpoint_actually_exits(controller):
    rom = Path('Gold 97 Reforged v6.1c.gbc')
    checkpoint = Path('data/checkpoints/run-001-20260921T144556495483Z-interval.state')
    if not rom.exists() or not checkpoint.exists():
        pytest.skip('requires the user-owned cartridge and elevator checkpoint')
    from pyboy import PyBoy

    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    adapter = Gold97Adapter(rom)
    try:
        with checkpoint.open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        s = adapter.snapshot(emulator).state
        assert (s.map_group, s.map_number) == (10, 12)
        controller.strategy.observe(s, (), True)
        terrain = Gold97CollisionMap.from_emulator(emulator, s)
        target = next(t for t in candidates(s, controller.memory, terrain) if t['kind'] == 'exit')
        options = target_options(target, s, controller.memory, terrain)
        assert set(options) == {'down'}
        emulator.button('down', 30)
        emulator.tick(60)
        s = adapter.snapshot(emulator).state
        # Elevator destinations are runtime-selected; the static header says 1F.
        assert s.area_name == 'Westport Dept Store 2F'
    finally:
        emulator.stop(save=False)


def test_saved_dock_checkpoint_boards_ferry(controller):
    rom = Path('Gold 97 Reforged v6.1c.gbc')
    checkpoint = Path('data/checkpoints/run-001-20260921T144420437508Z-encounter.state')
    if not rom.exists() or not checkpoint.exists():
        pytest.skip('requires the user-owned cartridge and dock checkpoint')
    from pyboy import PyBoy

    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    adapter = Gold97Adapter(rom)
    controller.route = RouteProgress(set(range(1, 11)))
    selected = False
    try:
        with checkpoint.open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        emulator.tick(100)  # Finish the checkpoint's in-progress step to (8, 15).
        emulator.button_press('left')
        for _ in range(60):
            emulator.tick()
            if adapter.snapshot(emulator).state.x == 7:
                break
        emulator.button_release('left')
        emulator.tick(30)
        emulator.button('down', 20)
        emulator.tick(40)
        for _ in range(40):
            s = adapter.snapshot(emulator).state
            if (s.map_group, s.map_number) == (14, 2):
                break
            options = controller._options(s, (), False)
            action = next(iter(options))
            selected |= 'Take the ferry' in options[action]
            emulator.button(action, 20)
            emulator.tick(100)
        assert selected
        assert (s.map_group, s.map_number) == (14, 2)
    finally:
        emulator.stop(save=False)
