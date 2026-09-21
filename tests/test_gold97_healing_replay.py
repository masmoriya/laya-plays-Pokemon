"""Opt-in cartridge proof that the nurse interaction actually restores the party."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_input import press_action, release_restored_buttons, renew_movement
from jpp.agent.gold97_services import fully_recovered, is_center
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_collision import Gold97CollisionCache
from jpp.terrain_capture import overworld_ready, visible_prompt


@pytest.mark.parametrize("approach", [False, True])
def test_nurse_heals_across_counter(tmp_path, approach):
    rom = os.environ.get('JPP_HEAL_TEST_ROM')
    checkpoint = os.environ.get('JPP_HEAL_TEST_STATE')
    if not rom or not checkpoint:
        pytest.skip('Set JPP_HEAL_TEST_ROM and JPP_HEAL_TEST_STATE for cartridge replay')
    from pyboy import PyBoy

    emulator = PyBoy(rom, window='null', sound_emulated=False)
    def unexpected_decision(branch):
        pytest.fail(f"Unexpected policy request: {actions}; {branch.state}")

    controller = Gold97Controller('heal-proof', database=tmp_path / 'proof.sqlite',
                                  vision_enabled=False, policy=SimpleNamespace(decide=unexpected_decision))
    adapter = Gold97Adapter(rom)
    cache = Gold97CollisionCache()
    active = None
    actions = []
    heal_attempts = 0
    try:
        with Path(checkpoint).open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        if approach:
            # Walk away using real input, then let recovery approach the desk.
            emulator.button_press("down")
            emulator.tick(24)
            emulator.button_release("down")
            emulator.tick(16)
            assert adapter.snapshot(emulator).state.y > 3
        assert not fully_recovered(adapter.snapshot(emulator).state)
        for frame in range(2400):
            state = adapter.snapshot(emulator).state
            if fully_recovered(state) and not is_center(state):
                break
            terrain = cache.update(emulator, state)
            overworld = overworld_ready(emulator, state) and cache.ready
            action = controller.step(
                state, frame=emulator.screen.ndarray, overworld=overworld,
                terrain=terrain, prompt_visible=(visible_prompt(emulator, state)
                                                if cache.ready and not overworld else False))
            heal_attempts = max(heal_attempts, (controller.recovery or {}).get('attempts', 0))
            assert not controller.paused, (controller.pause_reason, actions, state.x, state.y)
            pressed = False
            if action:
                actions.append((frame, action))
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
        assert any(action == 'a' for _, action in actions), actions
        assert fully_recovered(state), actions
        assert heal_attempts == 1, actions
        assert not is_center(state), actions
        # Finishing the visit must not immediately schedule another one.
        for _ in range(3):
            assert controller._recovery_action(state, overworld=True) is None
            assert controller.recovery is None
    finally:
        controller.close()
        emulator.stop(save=False)
