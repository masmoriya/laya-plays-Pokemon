"""Real-cartridge regressions; copied saves and button input only."""
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

pytestmark = pytest.mark.skipif(not os.getenv('GOLD97_PASSAGE_STATE'),
                               reason='provide a real Teknos Port Passage checkpoint')


class OnlyLegalAction:
    def decide(self, branch):
        assert len(branch.options) == 1, branch.options
        return Decision(option=next(iter(branch.options)), request_made=False)


@pytest.mark.parametrize('open_party', [False, True])
def test_passage_stairs_and_carpet_reach_city_without_manual_recovery(tmp_path, open_party):
    from pyboy import PyBoy
    rom = tmp_path / 'isolated.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM','Gold 97 Reforged v6.1c.gbc'),rom)
    emulator = PyBoy(str(rom),window='null',sound_emulated=False)
    emulator.set_emulation_speed(0)
    owner = Gold97Controller('passage',database=tmp_path/'memory.sqlite',
                            policy=OnlyLegalAction(),vision_enabled=False)
    adapter, cache = Gold97Adapter(rom), Gold97CollisionCache()
    owner.route = RouteProgress(set(range(1,11)))
    owner.memory.world['route'] = owner.route.to_dict()
    try:
        with Path(os.environ['GOLD97_PASSAGE_STATE']).open('rb') as f:
            emulator.load_state(f)
        release_restored_buttons(emulator)
        emulator.tick(30,True)
        assert adapter.snapshot(emulator).state.area_name == 'Teknos Port Passage'
        if open_party:
            press_action(emulator,'start',menu=True); emulator.tick(120,True)
            # Supplied checkpoint's Start menu highlights the party entry.
            assert 'POK' in adapter.snapshot(emulator).state.screen_lines[4]
            press_action(emulator,'a',menu=True); emulator.tick(120,True)
            state = adapter.snapshot(emulator).state
            assert 'CANCEL' in '\n'.join(state.screen_lines)
            assert visible_prompt(emulator,state)
        held = None
        for _ in range(1800):
            state = adapter.snapshot(emulator).state
            if state.area_name == 'Teknos City':
                owner.route.observe(state)
                assert 11 in owner.route.completed
                return
            terrain = cache.update(emulator,state)
            world = overworld_ready(emulator,state) and cache.ready
            action = owner.step(state,entities=visible_entities(emulator,state),
                                overworld=world,terrain=terrain,
                                prompt_visible=visible_prompt(emulator,state) if not world else False)
            assert not owner.paused, owner.pause_reason
            if action:
                if held and held != action: emulator.button_release(held)
                press_action(emulator,action,menu=not world)
                held = action
            held = renew_movement(emulator,held,owner.held_action,
                                  overworld=world,in_battle=False,pressed=bool(action))
            emulator.tick(1,True)
            if owner.decision_future: time.sleep(.001)
        pytest.fail(f'Stalled at {state.area_name} {(state.x,state.y)}')
    finally:
        owner.close(); emulator.stop(save=False)
