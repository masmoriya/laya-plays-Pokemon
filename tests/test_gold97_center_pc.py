"""Center visits must finish without an unsolicited storage detour."""
from types import SimpleNamespace as NS

import numpy as np

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_roster_service import RosterService
from jpp.agent.gold97_screen import pc_screen
from jpp.terrain_capture import overworld_ready, visible_prompt
from test_gold97_healing import party_state


PC_LINES = ('BILL S PC', 'LAYA S PC', 'PROF. OAK S PC', 'TURN OFF', 'Access whose PC?')


def test_large_pc_menu_is_a_prompt_even_with_overworld_sprite_flag():
    state = party_state()
    state.screen_lines, state.screen_cursor = PC_LINES, (0, 0)
    emulator = NS(memory={0xC2CE: 1}, screen=NS(
        ndarray=np.full((144, 160, 4), 255, dtype=np.uint8)))
    assert pc_screen(state)
    assert not overworld_ready(emulator, state)
    assert visible_prompt(emulator, state)
    state.screen_lines = ('WITHDRAW PKMN', 'DEPOSIT PKMN', 'CHANGE BOX', 'SEE YA!')
    assert pc_screen(state)
    state.screen_lines = ('Welcome to our POK MON CENTER!',)
    assert not pc_screen(state)


def test_routine_heal_does_not_consider_box_rotation():
    owner = NS(terrain=object(), training=NS(data={}), recovery=None)
    state = party_state()
    assert RosterService(owner).step(state, True) == (False, None)


def test_restored_healthy_party_leaves_center_and_resumes_journey(tmp_path):
    controller = Gold97Controller('center-exit', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        state = party_state()
        state.y = 7
        assert controller._recovery_action(state, overworld=True) == 'down'
        assert controller.recovery['exit']
        state.map_number, state.area_name = 1, 'Westport'
        assert controller._recovery_action(state, overworld=True) is None
        assert controller.recovery is None
    finally:
        controller.close()


def test_incidental_pc_cancels_then_stops_when_screen_does_not_change(tmp_path):
    controller = Gold97Controller('pc-exit', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        state = party_state()
        state.screen_lines, state.screen_cursor = PC_LINES, (0, 0)
        controller.held_action = 'right'
        for _ in range(6):
            assert controller._scripted_step(state, overworld=False, prompt_visible=False) == 'b'
            assert controller.held_action is None
        assert controller._scripted_step(state, overworld=False) is None
        assert controller.paused
        assert 'did not change' in controller.pause_reason
    finally:
        controller.close()
