"""Opt-in real-cartridge regression from a save outside Pagota's Center."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_input import press_action, release_restored_buttons, renew_movement
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_collision import Gold97CollisionCache
from jpp.terrain_capture import overworld_ready, visible_prompt


def test_real_center_door_transition(tmp_path):
    rom = os.environ.get('JPP_DOOR_TEST_ROM')
    checkpoint = os.environ.get('JPP_DOOR_TEST_STATE')
    if not rom or not checkpoint:
        pytest.skip('Set JPP_DOOR_TEST_ROM and JPP_DOOR_TEST_STATE for cartridge replay')
    from pyboy import PyBoy

    emulator = PyBoy(rom, window='null', sound_emulated=False)
    controller = Gold97Controller('door-proof', database=tmp_path / 'proof.sqlite',
                                  vision_enabled=False, policy=SimpleNamespace())
    adapter = Gold97Adapter(rom)
    cache = Gold97CollisionCache()
    active = None
    positions = []
    try:
        with Path(checkpoint).open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        for _ in range(300):
            state = adapter.snapshot(emulator).state
            position = (state.map_group, state.map_number, state.x, state.y)
            if not positions or positions[-1] != position:
                positions.append(position)
            if position[:2] == (9, 7):
                break
            terrain = cache.update(emulator, state)
            overworld = overworld_ready(emulator, state) and cache.ready
            action = controller.step(
                state, frame=emulator.screen.ndarray, overworld=overworld,
                terrain=terrain, prompt_visible=(visible_prompt(emulator, state)
                                                if cache.ready and not overworld else False))
            pressed = False
            if action:
                if active and active != action:
                    emulator.button_release(active)
                if active != action:
                    active = action
                    press_action(emulator, action, menu=not overworld)
                    pressed = True
            active = renew_movement(emulator, active, controller.held_action,
                                    overworld=overworld, in_battle=state.in_battle,
                                    pressed=pressed)
            emulator.tick(1)
        assert positions == [(9, 2, 28, 29), (9, 2, 27, 29),
                             (9, 2, 27, 28), (9, 7, 5, 7)]
    finally:
        controller.close()
        emulator.stop(save=False)
