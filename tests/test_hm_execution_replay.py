"""Real saved-game proof: menu inputs only, no cartridge memory writes."""
import os
from pathlib import Path
import shutil

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_input import press_action, release_restored_buttons
from jpp.gold97_adapter import Gold97Adapter
from jpp.route_progress import RouteProgress
from jpp.terrain_capture import overworld_ready
from jpp.agent.object_memory import classify


def test_owned_strength_is_taught_and_activated_through_real_menus(tmp_path):
    checkpoint = os.getenv('GOLD97_HM_STATE')
    if not checkpoint:
        pytest.skip('requires a real overworld save with an owned, untaught HM04')
    from pyboy import PyBoy
    rom = tmp_path / 'isolated.gbc'
    shutil.copyfile('Gold 97 Reforged v6.1c.gbc', rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    adapter = Gold97Adapter(rom)
    owner = Gold97Controller('hm-replay', database=tmp_path / 'memory.sqlite', vision_enabled=False)
    owner.route = RouteProgress(set(range(1, 12)))
    try:
        with Path(checkpoint).open('rb') as stream:
            emulator.load_state(stream)
        release_restored_buttons(emulator)
        emulator.tick(60, True)
        initial = adapter.snapshot(emulator).state
        assert 'Strength' in initial.owned_hms
        assert not any('Strength' in mon.moves for mon in initial.party)
        started = False
        for _ in range(150):
            state = adapter.snapshot(emulator).state
            world = overworld_ready(emulator, state)
            owner.unknown_frames = 20
            action = owner._scripted_step(state, overworld=world, prompt_visible=True)
            started |= owner.hm_teaching.phase is not None
            assert not owner.paused, owner.pause_reason
            if started and owner.hm_teaching.phase is None:
                break
            if action:
                assert action in {'start', 'a', 'b', 'up', 'down', 'left', 'right'}
                press_action(emulator, action, menu=not world)
            emulator.tick(60, True)
        else:
            pytest.fail('HM teaching did not finish')
        plan = owner.hm_teaching.plan
        learned = next(mon for mon in state.party if mon.identity == plan['identity'])
        assert 'Strength' in learned.moves
        assert state.owned_hms == initial.owned_hms  # HMs are reusable.
        for before, after in zip(initial.party, state.party):
            if after.identity != learned.identity:
                assert after.moves == before.moves
        # Exercise the actual field-menu executor independently of navigation.
        npc = {'id': 'replay-obstacle', 'cell': [state.x, state.y],
               'pages': ['A POKEMON may be able to move this.'], 'outcome': 'unresolved'}
        field = owner.strategy.field_action
        assert field.start(state, npc, owner.memory)
        for _ in range(125):
            state = adapter.snapshot(emulator).state
            world = overworld_ready(emulator, state)
            action = field.step(state, world)
            if not field.phase:
                break
            if action:
                press_action(emulator, action, menu=True)
            emulator.tick(60, True)
        assert not field.phase and not field.error, field.error
        assert state.strength_active is True
    finally:
        owner.close()
        emulator.stop(save=False)


def test_activated_strength_pushes_observed_cart_in_actual_save(tmp_path):
    checkpoint = os.getenv('GOLD97_STRENGTH_STATE')
    if not checkpoint:
        pytest.skip('requires a real save facing a movable cart with Strength active')
    from pyboy import PyBoy
    rom = tmp_path / 'isolated.gbc'
    shutil.copyfile('Gold 97 Reforged v6.1c.gbc', rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    adapter = Gold97Adapter(rom)
    owner = Gold97Controller('push-replay', database=tmp_path / 'memory.sqlite', vision_enabled=False)
    try:
        with Path(checkpoint).open('rb') as stream:
            emulator.load_state(stream)
        release_restored_buttons(emulator)
        emulator.tick(60, True)
        state = adapter.snapshot(emulator).state
        assert state.strength_active
        from jpp.agent.gold97_navigation import STEPS
        direction = state.player_facing
        dx, dy = STEPS[direction]
        obj = next(obj for obj in state.overworld_objects
                   if obj[1:] == (state.x + dx, state.y + dy))
        press_action(emulator, 'a', menu=True)
        emulator.tick(240, True)
        dialogue = adapter.snapshot(emulator).state
        text = ' '.join(line.strip() for line in dialogue.screen_lines[12:] if line.strip())
        assert 'may' in text and 'moved' in text
        press_action(emulator, 'a', menu=True)
        emulator.tick(120, True)
        state = adapter.snapshot(emulator).state
        assert overworld_ready(emulator, state)
        key = f'{state.map_group:02X}:{state.map_number:02X}'
        npc = classify({'id': key + '/' + obj[0], 'map': key, 'cell': list(obj[1:]),
                        'pages': [text], 'visible': True, 'status': 'pending'})
        assert npc['category'] == 'obstacle'
        owner.strategy.data['npcs'][npc['id']] = npc
        owner.strategy.observations.state = state
        owner.strategy.target = {'id': npc['id'], 'kind': 'talk', 'map': key,
                                 'cell': [state.x, state.y], 'direction': direction,
                                 'label': 'Investigate the observed cart'}
        for _ in range(26):
            options = owner.strategy.options(state, None)
            if options:
                break
        assert options == {direction: 'Push the obstacle with active Strength'}
        owner.strategy.chosen(direction)
        press_action(emulator, direction)
        emulator.tick(36, True)
        emulator.button_release(direction)
        emulator.tick(60, True)
        after = adapter.snapshot(emulator).state
        moved = next(item for item in after.overworld_objects if item[0] == obj[0])
        assert moved[1:] == (obj[1] + dx, obj[2] + dy)
    finally:
        owner.close()
        emulator.stop(save=False)
