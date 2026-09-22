"""Regressions found while observing real port and party-menu checkpoints."""
from types import SimpleNamespace as NS

import numpy as np
import pytest

from test_journey_strategy import controller as controller, state
from jpp.agent.journey_exits import exit_candidates
from jpp.gold97_collision import Gold97CollisionMap
from jpp.terrain_capture import visible_prompt


def test_party_menu_is_actionable_despite_mostly_white_background():
    lines = [''] * 18
    lines[1], lines[2], lines[13], lines[16] = 'HOPPIP 30 30', '10', 'CANCEL', 'Choose a POK MON!'
    s = NS(screen_lines=tuple(lines), screen_cursor=(0, 1))
    frame = np.full((144, 160, 4), 255, dtype=np.uint8)
    frame[::5, ::5, :3] = 0
    emulator = NS(screen=NS(ndarray=frame))
    assert visible_prompt(emulator, s)
    frame[:] = 255
    assert not visible_prompt(emulator, s)  # Fade still has stale tile text.


@pytest.mark.parametrize('tile,direction', [(0x70,'down'), (0x76,'left'), (0x78,'up'), (0x7e,'right')])
def test_interior_warp_carpet_keeps_its_exit_direction(controller, tile, direction):
    s = state()
    s.map_exits = ((2, 2, '', 4, 5),)
    cells = bytearray(36); cells[14] = tile
    terrain = Gold97CollisionMap((9,2), 6, 6, bytes(cells))
    targets = exit_candidates(s, controller.memory, {(2,2):'right'}, (), terrain)
    assert targets[0]['direction'] == direction
    s.x, s.y = 2, 2
    assert exit_candidates(s, controller.memory, {(2,2):None}, (), terrain)


def test_wait_for_stairs_then_replan_on_same_map_arrival(controller):
    s = state()
    strategy = controller.strategy
    strategy.observe(s, (), True)
    strategy.target = {'id':'stairs', 'kind':'exit', 'cell':[1,1],
                       'direction':'', 'destination_key':'09:02','map':'09:02'}
    terrain = Gold97CollisionMap((9,2), 6, 6, bytes(36))
    assert strategy.options(s, terrain) == {}
    assert strategy.target['id'] == 'stairs'
    s.x, s.y = 4, 4
    strategy.observe(s, (), True)
    assert strategy.target is None
    assert any(event['kind']=='subgoal_completed' and event['detail']=='stairs'
               for event in strategy.data['events'])
    assert not controller.memory.experience.failures(controller.route.now)


def test_yes_choice_moves_to_yes_and_remains_committed():
    from jpp.agent.gold97_choices import dialogue_options, answer_button, choice_key
    s = NS(map_group=14, map_number=1, screen_lines=('YES','NO','Take the ferry?'), screen_cursor=(1,1))
    owner = NS()
    assert set(dialogue_options(owner,s)) == {'yes','no'}
    owner.dialogue_choice = (choice_key(s),'yes')
    assert answer_button(s,'yes') == 'up'
    assert dialogue_options(owner,s) == {'up':'Confirm yes'}
    s.screen_cursor = (1,0)
    assert dialogue_options(owner,s) == {'a':'Confirm yes'}
    s.screen_lines = ('Thanks!',)
    assert dialogue_options(owner,s) is None
    assert owner.dialogue_choice is None


def test_full_screen_shop_is_actionable_without_accepting_a_fade():
    s = NS(screen_cursor=(1,4), screen_lines=('POK BALL','200')+('',)*16)
    frame = np.full((144,160,4),255,dtype=np.uint8)
    frame[::5,::5,:3] = 0
    emulator = NS(memory={0xC2CE:0}, screen=NS(ndarray=frame))
    assert visible_prompt(emulator,s)
    frame[:] = 255
    assert not visible_prompt(emulator,s)


def test_fade_map_id_change_does_not_lose_arrival_direction(controller):
    s = state()
    controller.strategy.observe(s, (), True)
    s.map_group, s.map_number = 10, 1
    controller.strategy.observe(s, (), False)
    controller.strategy.observe(s, (), True)
    assert controller.strategy.arrived_from == '09:02'


def test_return_door_is_removed_when_forward_tasks_exist(controller):
    strategy = controller.strategy
    strategy.arrived_from = '09:01'
    ranked = strategy.prioritize_forward_routes([
        {'id':'back','kind':'exit','destination_key':'09:01','journey_reward':25},
        {'id':'forward','kind':'talk','journey_reward':28},
    ])
    assert ranked[0]['id'] == 'forward'
    assert ranked[1]['recent_return']


def test_temporary_npc_block_does_not_become_a_permanent_wall(controller, monkeypatch):
    from jpp.agent.journey_targets import paths
    monkeypatch.setattr('jpp.agent.gold97_memory.time.time', lambda: 100)
    s = state()
    terrain = Gold97CollisionMap((9,2), 6, 6, bytes(36))
    controller.memory.move_result('09:02', (1,1), 'up', (1,1))
    assert [[1,1], 'up'] in controller.memory.map('09:02')['blocked']
    monkeypatch.setattr('jpp.agent.gold97_memory.time.time', lambda: 131)
    paths(s, controller.memory, terrain)
    assert [[1,1], 'up'] not in controller.memory.map('09:02')['blocked']
    assert terrain.allows((1,0), 'up')


def test_known_goal_route_wins_after_a_supply_detour(controller):
    from jpp.agent.journey_routes import rank_known_routes
    s = state()
    controller.strategy.data['map_exits'] = {'09:02':['09:01','09:03'], '09:01':['09:0A']}
    targets = [
        {'id':'unrelated','kind':'exit','destination_key':'09:03','journey_reward':75},
        {'id':'resume','kind':'exit','destination_key':'09:01','journey_reward':25},
    ]
    ranked = rank_known_routes(targets, s, controller.memory,
                               'Fight your rival near the Westport gate', 100)
    assert ranked[0]['id'] == 'resume'
    assert ranked[0]['goal_route']
    controller.strategy.arrived_from = '09:01'
    assert not controller.strategy.prioritize_forward_routes(ranked)[0].get('recent_return')


def test_potion_use_popup_ignores_inventory_text_to_its_left():
    from jpp.agent.gold97_battle_menus import heal_step
    lines = [' ' * 20] * 18
    lines[8] = '        X ACC  USE  '
    lines[10] = '        ESCAP  QUIT '
    executor = NS(phase='use_potion', confirmed=None)
    s = NS(screen_cursor=(14,8))
    assert heal_step(executor, s, lines, 'new-frame', ()) == 'a'


def test_battle_loss_text_remains_actionable_after_battle_flag_clears():
    lines = [''] * 18
    lines[14] = 'LAYA is out of'
    lines[16] = 'useable POK MON!'
    s = NS(screen_lines=tuple(lines), screen_cursor=None)
    frame = np.full((144,160,4),255,dtype=np.uint8)
    frame[::5,::5,:3] = 0
    emulator = NS(memory={0xC2CE:0}, screen=NS(ndarray=frame))
    assert visible_prompt(emulator,s)
    frame[:] = 255
    assert not visible_prompt(emulator,s)


def test_gym_recovery_uses_observed_exit_to_a_town_with_a_center():
    from jpp.agent.gold97_services import center_retreat_target
    s = NS(map_group=10, map_number=24, x=5, y=8, map_height=18,
           map_exits=((4,17,'',10,1),))
    assert center_retreat_target(s) == ((4,17),'down')


def test_potion_result_advances_without_a_menu_cursor():
    from jpp.agent.gold97_battle_menus import heal_step
    executor = NS(phase='heal_result', confirmed=None)
    assert heal_step(executor, NS(screen_cursor=None), ('Recovered 19HP.',), 'result', ()) == 'a'
    assert heal_step(executor, NS(screen_cursor=None), ('Recovered 19HP.',), 'result', ()) is None
