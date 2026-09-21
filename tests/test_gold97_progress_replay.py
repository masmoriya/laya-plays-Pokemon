"""Opt-in replays use only copied ROMs, isolated ledgers, and real checkpoints."""
import os
from pathlib import Path
import shutil
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_input import press_action, release_restored_buttons
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_rewards import RewardLedger
from jpp.agent.gold97_party import PartyReorder
from jpp.agent.gold97_pc import PCTransfer
from jpp.gold97_adapter import Gold97Adapter
from jpp.terrain_capture import overworld_ready
from jpp.route_progress import RouteProgress


def load(tmp_path, checkpoint):
    from pyboy import PyBoy
    rom=tmp_path/'isolated.gbc'
    shutil.copyfile(os.getenv('GOLD97_ROM','Gold 97 Reforged v6.1c.gbc'),rom)
    emulator=PyBoy(str(rom),window='null',sound_emulated=False)
    emulator.set_emulation_speed(0)
    with Path(checkpoint).open('rb') as handle: emulator.load_state(handle)
    release_restored_buttons(emulator)
    return emulator, Gold97Adapter(rom)


@pytest.mark.skipif(not os.getenv('GOLD97_WILD_STATE'),reason='provide GOLD97_WILD_STATE')
def test_real_eligible_capture_and_ball_consumption(tmp_path):
    emulator, adapter=load(tmp_path,os.environ['GOLD97_WILD_STATE'])
    memory=Gold97Memory('replay',tmp_path/'isolated.sqlite')
    ledger, route=RewardLedger(memory),RouteProgress()
    ex=BattleExecutor()
    owner=NS(battle_strategy=Gold97BattleStrategy(),battle_target=None,battle_switch_phase=None,paused=False)
    owner._set_provider_event=lambda text:None
    owner.pause=pytest.fail
    initial=adapter.snapshot(emulator).state
    assert initial.battle.kind=='wild'
    target=initial.battle.opponent.species_id
    try:
        for _ in range(1200):
            state=adapter.snapshot(emulator).state
            ledger.observe(state,route)
            if not state.in_battle:
                assert target in state.pokedex_caught_ids
                assert state.poke_ball_count < initial.poke_ball_count
                assert ledger.summary()['points']>=25
                return
            button=ex.step(owner,state)
            if button:press_action(emulator,button,menu=True)
            emulator.tick(30,True)
        pytest.fail('Capture did not finish within the bounded replay')
    finally:
        memory.close();emulator.stop(save=False)


@pytest.mark.skipif(not os.getenv('GOLD97_PC_STATE'),reason='provide GOLD97_PC_STATE at a PC facing it with a stored mon')
def test_real_pc_withdraw_reorder_and_cross_box_deposit(tmp_path):
    emulator, adapter=load(tmp_path,os.environ['GOLD97_PC_STATE'])
    initial=adapter.snapshot(emulator).state
    assert initial.storage_verified and initial.box_roster and len(initial.party)<6
    target=initial.box_roster[-1]
    def finish(executor):
        for _ in range(240):
            state=adapter.snapshot(emulator).state
            button=executor.step(state,overworld_ready(emulator,state))
            if button:press_action(emulator,button,menu=True)
            emulator.tick(45,True)
            if executor.phase is None:
                assert not executor.error
                return adapter.snapshot(emulator).state
        pytest.fail(f'Menu stalled: {executor.phase}, {executor.error}')
    try:
        transfer=PCTransfer()
        assert transfer.start(initial,{'kind':'withdraw','identity':target.identity,'box':target.storage_box})
        press_action(emulator,'a',menu=True);emulator.tick(90,True)
        state=finish(transfer)
        assert transfer.completed and any(m.identity==target.identity for m in state.party)
        reorder=PartyReorder();index=next(i for i,m in enumerate(state.party) if m.identity==target.identity)
        assert reorder.start(state,index)
        state=finish(reorder)
        assert state.party[0].identity==target.identity
        transfer=PCTransfer()
        assert transfer.start(state,{'kind':'deposit','identity':target.identity,'box':(target.storage_box+1)%14})
        press_action(emulator,'a',menu=True);emulator.tick(90,True)
        state=finish(transfer)
        assert transfer.completed
        assert {m.identity for m in state.party}=={m.identity for m in initial.party}
    finally:emulator.stop(save=False)
