"""Opt-in real-cartridge escape proof, using temporary copies only."""
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_input import press_action, release_restored_buttons
from jpp.gold97_adapter import Gold97Adapter


@pytest.mark.skipif(not os.getenv('GOLD97_WILD_STATE'), reason='provide GOLD97_WILD_STATE')
def test_saved_wild_encounter_escapes_and_preserves_reserves(tmp_path):
    from pyboy import PyBoy
    rom = tmp_path / 'escape.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'), rom)
    emulator = PyBoy(str(rom), window='null', sound_emulated=False)
    emulator.set_emulation_speed(0)
    adapter, executor = Gold97Adapter(rom), BattleExecutor()
    owner = SimpleNamespace(battle_strategy=Gold97BattleStrategy(), battle_target=None,
                            battle_switch_phase=None, pause=pytest.fail,
                            _set_provider_event=lambda text: None)
    actions = set()
    try:
        with Path(os.environ['GOLD97_WILD_STATE']).open('rb') as handle:
            emulator.load_state(handle)
        release_restored_buttons(emulator)
        initial = adapter.snapshot(emulator).state
        assert initial.mechanics_verified and initial.battle.kind == 'wild'
        assert owner.battle_strategy.plan(initial).kind == 'escape'
        for _ in range(600):
            state = adapter.snapshot(emulator).state
            if not state.in_battle:
                assert 'escape' in actions
                assert state.battle_result == 2
                assert sum(m.hp > 0 for m in state.party) == sum(m.hp > 0 for m in initial.party)
                return
            button = executor.step(owner, state)
            if executor.action:
                actions.add(executor.action.kind)
            if button:
                press_action(emulator, button, menu=True)
            emulator.tick(20, False)
        pytest.fail('Wild encounter did not exit within 12000 emulated frames')
    finally:
        emulator.stop(save=False)
