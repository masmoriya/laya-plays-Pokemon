"""Opt-in movement replay using a real Pagota checkpoint and isolated saves."""
import os
import shutil
import time
from pathlib import Path

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_input import press_action, release_restored_buttons, renew_movement
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_collision import Gold97CollisionCache
from jpp.policy import Decision
from jpp.route_progress import RouteProgress
from jpp.terrain_capture import overworld_ready, visible_entities, visible_prompt


class OnlyLegalAction:
    """Test guard: fail rather than invoke a model or choose among alternatives."""

    def decide(self, branch):
        assert len(branch.options) == 1, branch.options
        return Decision(option=next(iter(branch.options)), request_made=False)


@pytest.mark.skipif(not os.getenv('GOLD97_PAGOTA_STATE'), reason='provide GOLD97_PAGOTA_STATE after receiving Cut')
def test_pagota_checkpoint_reaches_route_102_without_npc_detours(tmp_path):
    from pyboy import PyBoy

    rom = tmp_path / 'isolated.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'), rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    emulator.set_emulation_speed(0)
    adapter = Gold97Adapter(rom)
    owner = Gold97Controller('replay', database=tmp_path / 'memory.sqlite',
                            vision_enabled=False, policy=OnlyLegalAction())
    actions = []
    try:
        with Path(os.environ['GOLD97_PAGOTA_STATE']).open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        initial = adapter.snapshot(emulator).state
        assert (initial.map_group, initial.map_number) == (9, 2)
        assert initial.received_cut_from_bill
        # The supplied checkpoint is at the Journey's seventh milestone.
        owner.route = RouteProgress(set(range(1, 7)))
        owner.memory.world['route'] = owner.route.to_dict()
        cache = Gold97CollisionCache()
        held = None
        for _ in range(1800):
            state = adapter.snapshot(emulator).state
            if (state.map_group, state.map_number) == (9, 1):
                assert actions and set(actions) <= {'up', 'down', 'left', 'right'}
                assert not owner.strategy.data['clues']
                return
            terrain = cache.update(emulator, state)
            world = overworld_ready(emulator, state) and cache.ready
            action = owner.step(
                state, entities=visible_entities(emulator, state), overworld=world,
                terrain=terrain, prompt_visible=(visible_prompt(emulator, state)
                                                if cache.ready and not world else False))
            assert not owner.paused, owner.pause_reason
            if action:
                actions.append(action)
                if held and held != action:
                    emulator.button_release(held)
                press_action(emulator, action, menu=not world or state.in_battle)
                held = action
            held = renew_movement(emulator, held, owner.held_action, overworld=world,
                                  in_battle=state.in_battle, pressed=bool(action))
            if owner.decision_future:
                time.sleep(.001)
            emulator.tick(1, True)
        pytest.fail(f'Journey stalled at {(state.x, state.y)}: {actions[-10:]}')
    finally:
        owner.close()
        emulator.stop(save=False)
