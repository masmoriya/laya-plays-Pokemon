"""Opt-in real-save regressions: no memory writes or scripted model choices."""
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


class SoleLegalAction:
    def decide(self, branch):
        assert len(branch.options) == 1, branch.options
        return Decision(option=next(iter(branch.options)), request_made=False)


@pytest.mark.parametrize('scenario', ['doll', 'sailor'])
@pytest.mark.parametrize('frames_per_tick', [1, 2, 4])
def test_actual_menu_cancel_and_npc_approach(tmp_path, scenario, frames_per_tick):
    checkpoint = os.getenv(f'GOLD97_{scenario.upper()}_STATE')
    if not checkpoint:
        pytest.skip('requires an actual saved interaction')
    from pyboy import PyBoy
    rom = tmp_path / 'isolated.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'), rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    emulator.set_emulation_speed(0)
    owner = Gold97Controller('interaction', database=tmp_path / 'memory.sqlite',
                            policy=SoleLegalAction(), vision_enabled=False)
    owner.route = RouteProgress(set(range(1, 11)))
    owner.memory.world['route'] = owner.route.to_dict()
    owner.strategy.data['enabled'] = False
    adapter, cache = Gold97Adapter(rom), Gold97CollisionCache()
    try:
        with Path(checkpoint).open('rb') as stream:
            emulator.load_state(stream)
        release_restored_buttons(emulator)
        initial = adapter.snapshot(emulator).state
        if scenario == 'doll':
            assert 'DOLL' in '\n'.join(initial.screen_lines)
            assert visible_prompt(emulator, initial)
        held, actions = None, []
        for _ in range(1600):
            state = adapter.snapshot(emulator).state
            terrain = cache.update(emulator, state)
            world = overworld_ready(emulator, state) and cache.ready
            prompt = visible_prompt(emulator, state)
            if (scenario == 'doll' and world) or (scenario == 'sailor' and prompt):
                assert state.money == initial.money
                if scenario == 'doll':
                    assert actions[0] == 'b'
                else:
                    assert actions[-2:] == ['down', 'a']
                    emulator.tick(120, True)
                    text = '\n'.join(adapter.snapshot(emulator).state.screen_lines)
                    assert 'Welcome to the' in text and 'WESTPORT CITY' in text, text
                return
            action = owner.step(state, entities=visible_entities(emulator, state),
                                overworld=world, terrain=terrain,
                                prompt_visible=prompt if not world else False)
            assert not owner.paused, owner.pause_reason
            if action:
                actions.append(action)
                if held and held != action:
                    emulator.button_release(held)
                press_action(emulator, action, menu=not world)
                held = action
            held = renew_movement(emulator, held, owner.held_action,
                                  overworld=world, in_battle=False, pressed=bool(action))
            emulator.tick(frames_per_tick, True)
            if owner.decision_future:
                time.sleep(.001)
        pytest.fail(f'{scenario} stalled: {actions} {state.screen_lines}')
    finally:
        owner.close()
        emulator.stop(save=False)
