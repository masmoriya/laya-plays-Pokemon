"""Opt-in battle replay on a temporary ROM copy; never writes the player's save."""
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_input import press_action, release_restored_buttons
from jpp.gold97_adapter import Gold97Adapter


@pytest.mark.skipif(not os.getenv('GOLD97_BATTLE_STATE'), reason='provide GOLD97_BATTLE_STATE')
def test_saved_trainer_battle_completes_without_model_calls(tmp_path):
    from pyboy import PyBoy
    original = Path(os.getenv('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'))
    rom = tmp_path / 'battle.gbc'
    shutil.copyfile(original, rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    emulator.set_emulation_speed(0)
    adapter, executor = Gold97Adapter(rom), BattleExecutor()
    owner = SimpleNamespace(battle_strategy=Gold97BattleStrategy(), battle_target=None,
                            battle_switch_phase=None, paused=False)
    owner._set_provider_event = lambda text: None
    def pause(text):
        snapshot = adapter.snapshot(emulator).state
        pytest.fail(f"{text}: {snapshot.battle_menu_kind}, {snapshot.screen_lines}, "
                    f"cursor={snapshot.screen_cursor}, action={executor.action}, phase={executor.phase}")
    owner.pause = pause
    try:
        with Path(os.environ['GOLD97_BATTLE_STATE']).open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        initial = adapter.snapshot(emulator).state
        assert initial.mechanics_verified and initial.battle.kind == 'trainer'
        observed = set()
        for _ in range(1200):
            state = adapter.snapshot(emulator).state
            observed.add(state.battle_menu_kind)
            if not state.in_battle:
                assert any(mon.hp > 0 for mon in state.party)
                assert state.battle_result == 0
                print("Observed battle menus:", sorted(str(value) for value in observed))
                return
            button = executor.step(owner, state)
            if button:
                press_action(emulator, button, menu=True)
            emulator.tick(20, False)
        pytest.fail('Trainer battle did not finish within 24000 emulated frames')
    finally:
        emulator.stop(save=False)


@pytest.mark.skipif(not os.getenv('GOLD97_BATTLE_STATE'), reason='provide GOLD97_BATTLE_STATE')
def test_already_out_message_recovers_on_cartridge(tmp_path):
    from pyboy import PyBoy
    from jpp.agent.gold97_battle_executor import party_step, root_step
    rom = tmp_path / 'battle.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'), rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    emulator.set_emulation_speed(0)
    adapter, executor = Gold97Adapter(rom), BattleExecutor()
    owner = SimpleNamespace(battle_strategy=Gold97BattleStrategy(), battle_target=None,
                            battle_switch_phase=None, paused=False)
    owner._set_provider_event = lambda text: None
    owner.pause = pytest.fail
    phase = 'settle'
    try:
        with Path(os.environ['GOLD97_BATTLE_STATE']).open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        for _ in range(600):
            state = adapter.snapshot(emulator).state
            text = ' '.join(' '.join(state.screen_lines).upper().split())
            if phase == 'settle' and state.battle_menu_kind == 'command':
                phase = 'open_party'
            if phase == 'open_party':
                button = root_step(state.battle_menu_cursor, (2, 1))
                if state.battle_menu_kind == 'party':
                    phase = 'select_active'
            if phase == 'select_active':
                assert state.active_slot is not None
                button = party_step(state.battle_menu_cursor, state.active_slot)
                # The cartridge opens SWITCH/STATS after selecting a partner.
                # Complete that visible submenu before expecting ALREADY OUT.
                if state.battle_menu_kind == 'party_action':
                    row = next(i for i, line in enumerate(state.screen_lines) if 'SWITCH' in line)
                    cursor = state.battle_menu_cursor
                    button = (None if cursor is None else 'a' if cursor[1] == row else
                              'down' if cursor[1] < row else 'up')
                if 'ALREADY OUT' in text:
                    phase = 'recover'
                    executor.reset()
            if phase == 'settle' or phase == 'recover':
                button = executor.step(owner, state)
            if phase == 'recover' and state.battle_menu_kind == 'command':
                assert state.battle.active.hp > 0
                return
            if button:
                press_action(emulator, button, menu=True)
            emulator.tick(20, False)
        pytest.fail(f'Already-out recovery stopped in {phase}: {text}')
    finally:
        emulator.stop(save=False)
