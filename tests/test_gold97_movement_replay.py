"""Opt-in cartridge proof: an accepted route must turn and stop at every speed."""
import os
from pathlib import Path
import shutil
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_input import press_action, release_restored_buttons
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.journey_targets import paths, target_options
from jpp.agent.route_execution import committed_heading
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_collision import Gold97CollisionMap
from jpp.terrain_capture import overworld_ready, visible_prompt

pytestmark = pytest.mark.skipif(not os.getenv('GOLD97_MOVEMENT_STATE'),
                                reason='Requires the real Route 120 (40,7) checkpoint')


@pytest.mark.parametrize('stride', [1, 2, 4, 8])
@pytest.mark.parametrize('phase', [0, 3, 7])
def test_native_route_turns_and_stops_without_oscillation(tmp_path, stride, phase):
    from pyboy import PyBoy
    rom = tmp_path/'isolated.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'), rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    memory = Gold97Memory('movement', tmp_path/'memory.sqlite')
    adapter = Gold97Adapter(rom)
    emulator.set_emulation_speed(0)
    try:
        with Path(os.environ['GOLD97_MOVEMENT_STATE']).open('rb') as f:
            emulator.load_state(f)
        release_restored_buttons(emulator)
        # Close the checkpoint's existing text/menu using native input only.
        for _ in range(40):
            emulator.tick(60, True)
            state = adapter.snapshot(emulator).state
            if overworld_ready(emulator, state) and not visible_prompt(emulator, state):
                break
            press_action(emulator, 'b', menu=True)
        assert state.area_name == 'Route 120' and (state.x, state.y) == (40, 7)
        assert overworld_ready(emulator, state) and not visible_prompt(emulator, state)
        terrain = Gold97CollisionMap.from_emulator(emulator, state)
        target = dict(id='verified-test-route', kind='explore', map='04:07',
                      cell=[42, 9], direction='', label='Reach the visible tile')
        assert tuple(target['cell']) in paths(state, memory, terrain, prefer_new=False)
        owner = NS(paused=False, terrain=terrain, memory=memory,
                   strategy=NS(target=target, future=None, data={'npcs': {}},
                               observations=NS(pending=None)))
        emulator.tick(phase, True) if phase else None
        held, trail = None, []
        for _ in range(800 // stride):
            state = adapter.snapshot(emulator).state
            position = state.x, state.y
            if not state.player_moving:
                if not trail or trail[-1] != position:
                    trail.append(position)
                assert trail.count(position) < 3, f'Oscillating at {position}: {trail}'
                if position == tuple(target['cell']):
                    if held:
                        emulator.button_release(held)
                    emulator.tick(32, True)
                    final = adapter.snapshot(emulator).state
                    assert (final.x, final.y) == position  # No already-queued extra step.
                    return
                action = next(iter(target_options(target, state, memory, terrain)))
                if held != action:
                    if held:
                        emulator.button_release(held)
                    press_action(emulator, action)
                    held = action
            elif held and not committed_heading(owner, state, held):
                emulator.button_release(held)
                held = None
            emulator.tick(stride, True)
        pytest.fail(f'Route did not arrive: {trail}')
    finally:
        memory.close()
        emulator.stop(save=False)
