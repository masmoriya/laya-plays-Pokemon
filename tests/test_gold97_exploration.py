"""Discovery rewards and forward exploration without trapping return routes."""

from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_rewards import RewardLedger
from jpp.agent.journey_knowledge import knowledge
from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap


@pytest.fixture
def memory(tmp_path):
    value = Gold97Memory('exploration', tmp_path / 'run.sqlite')
    knowledge(value)
    yield value
    value.close()


def state(number=2, **changes):
    values = dict(map_group=9, map_number=number, x=1, y=1,
                  map_width=6, map_height=6, area_name=f'Area {number}',
                  mechanics_verified=True, in_battle=False, map_exits=())
    return NS(**(values | changes))


def test_discovery_rewards_once_across_revisit_restore_and_restart(memory):
    ledger = RewardLedger(memory)
    ledger.observe_exploration(state(), overworld=True)
    memory.checkpoint('start')
    assert ledger.summary()['points'] == 0
    ledger.observe_exploration(state(3), overworld=True)
    assert ledger.summary()['points'] == 50
    ledger.observe_exploration(state(), overworld=True)
    ledger.observe_exploration(state(3), overworld=True)
    memory.restore('start')
    ledger = RewardLedger(memory)
    ledger.observe_exploration(state(3), overworld=True)
    assert ledger.summary()['points'] == 50
    ledger.observe_exploration(state(4), overworld=True)
    assert ledger.summary()['points'] == 100
    assert ledger.summary()['recent'][-1]['kind'] == 'discovery'


def test_existing_maps_are_baselined_without_reward(memory):
    memory.visited('09:03', (1, 1))
    memory.map('09:04')  # Creating an empty map is not evidence of a visit.
    ledger = RewardLedger(memory)
    ledger.observe_exploration(state(), overworld=True)
    ledger.observe_exploration(state(3), overworld=True)
    assert ledger.summary()['points'] == 0
    ledger.observe_exploration(state(4), overworld=True)
    assert ledger.summary()['points'] == 50


@pytest.mark.parametrize('changes,overworld', [
    ({}, False), ({'in_battle': True}, True),
    ({'mechanics_verified': False}, True), ({'x': None}, True),
    ({'x': 6}, True), ({'map_group': 0}, True),
])
def test_unverified_or_transitional_positions_do_not_claim_discoveries(memory, changes, overworld):
    ledger = RewardLedger(memory)
    ledger.observe_exploration(state(), overworld=True)
    ledger.observe_exploration(state(3, **changes), overworld=overworld)
    assert ledger.summary()['points'] == 0
    assert '09:03' not in ledger.data['discovered_maps']


def test_new_exit_precedes_local_exploration_and_removes_return(memory):
    memory.visited('09:01', (1, 1))
    memory.visited('09:02', (1, 1))
    s = state(map_exits=((0, 1, 'left', 9, 1), (5, 1, 'right', 9, 3)))
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    targets = candidates(s, memory, terrain)
    assert targets[0]['destination'] == '09:03'
    assert targets[0]['unvisited_destination']
    assert not any(t.get('destination') == '09:01' for t in targets)
    assert any(t['kind'] == 'explore' for t in targets)
    memory.visited('09:03', (1, 1))
    targets = candidates(s, memory, terrain)
    assert {t['destination'] for t in targets if t['kind'] == 'exit'} == {'09:01', '09:03'}


def test_observed_return_connection_cannot_bypass_new_exit_preference(memory):
    memory.world['journey_strategy']['connections'] = [
        {'from': '09:01', 'to': '09:02', 'at': [5, 1],
         'arrival': [0, 1], 'direction': 'right'}]
    s = state(map_exits=((0, 1, 'left', 9, 1), (5, 1, 'right', 9, 3)))
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    exits = [t for t in candidates(s, memory, terrain) if t['kind'] == 'exit']
    assert [t['destination'] for t in exits] == ['09:03']


def test_unreachable_new_exit_does_not_suppress_only_way_back(memory):
    memory.visited('09:01', (1, 1))
    s = state(map_exits=((0, 1, 'left', 9, 1), (5, 1, 'right', 9, 3)))
    cells = bytearray(36)
    cells[11] = 7
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(cells))
    exits = [t for t in candidates(s, memory, terrain) if t['kind'] == 'exit']
    assert [t['destination'] for t in exits] == ['09:01']
