"""Visible mine interactions on a copy of the user's save, without RAM writes."""
import os
from pathlib import Path
import shutil

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_input import press_action, release_restored_buttons, renew_movement
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_collision import Gold97CollisionCache
from jpp.policy import Decision
from jpp.terrain_capture import overworld_ready, visible_entities, visible_prompt
from jpp.agent.journey_targets import candidates


class OnlyLegalAction:
    def decide(self, branch):
        self.last_options = branch.options
        assert len(branch.options) == 1, branch.options
        return Decision(option=next(iter(branch.options)), request_made=False)


def test_visible_girl_is_approached_faced_and_rescued(tmp_path):
    checkpoint = os.getenv('GOLD97_RESCUE_STATE')
    if not checkpoint:
        pytest.skip('requires an actual mine save with the girl and item visible')
    from pyboy import PyBoy
    rom = tmp_path / 'isolated.gbc'
    shutil.copyfile('Gold 97 Reforged v6.1c.gbc', rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    emulator.set_emulation_speed(0)
    owner = Gold97Controller('rescue', database=tmp_path / 'memory.sqlite',
                            policy=OnlyLegalAction(), vision_enabled=False)
    adapter, cache = Gold97Adapter(rom), Gold97CollisionCache()
    owner.training.data['enabled'] = False
    try:
        with Path(checkpoint).open('rb') as stream:
            emulator.load_state(stream)
        release_restored_buttons(emulator)
        emulator.tick(60, True)
        initial = adapter.snapshot(emulator).state
        terrain = cache.update(emulator, initial)
        owner.observe(initial, visible_entities(emulator, initial), True, terrain)
        targets = candidates(initial, owner.memory, owner.terrain)
        # Reproduce a committed cart plan when the girl is already visible.
        owner.strategy.target = next(target for target in targets
                                     if target.get('category') == 'obstacle')
        held, actions, pages = None, [], set()
        for _ in range(12000):  # Includes naturally encountered wild battles.
            state = adapter.snapshot(emulator).state
            terrain = cache.update(emulator, state)
            world = overworld_ready(emulator, state) and cache.ready
            prompt = visible_prompt(emulator, state)
            if not world:
                pages.add(' '.join(state.screen_lines[12:]))
            if 12 in state.story_milestones:
                assert 'a' in actions
                assert any('Grandpa' in page for page in pages)
                return
            action = owner.step(state, entities=visible_entities(emulator, state),
                                overworld=world, terrain=terrain, prompt_visible=prompt)
            if owner.paused:
                pytest.fail(f'{owner.pause_reason}; options={getattr(owner.policy, "last_options", None)}; '
                            f'position={(state.x, state.y)}; actions={actions[-20:]}; '
                            f'goal={owner.route.now}; npcs={owner.strategy.data["npcs"]}')
            if action:
                actions.append(action)
                if held and held != action:
                    emulator.button_release(held)
                press_action(emulator, action, menu=not world)
                held = action
            held = renew_movement(emulator, held, owner.held_action, overworld=world,
                                  in_battle=state.in_battle, pressed=bool(action))
            emulator.tick(1, True)
        with (tmp_path / 'stalled.state').open('wb') as stream:
            emulator.save_state(stream)
        pytest.fail(f'Rescue stalled at {(state.x, state.y)}: {actions[-30:]} '
                    f'world={world}, prompt={prompt}, pending={owner.strategy.observations.pending}, '
                    f'cooldown={owner.cooldown}, {state.screen_lines}')
    finally:
        owner.close()
        emulator.stop(save=False)
