from conftest import load_ram

from jpp import symbols as S
from jpp.decode import decode
from jpp.goals import GOALS, GoalStack
from jpp.loop import BattleLatch

import make_ram


def stack_at(ram, latch=None):
    stack = GoalStack()
    stack.advance(decode(bytes(ram)), latch or BattleLatch())
    return stack


def test_the_run_starts_on_leave_house():
    assert stack_at(make_ram.bedroom()).current.name == "leave_house"


def test_leaving_the_house_advances_to_get_starter():
    ram = make_ram.bedroom()
    ram[S.CUR_MAP] = S.PALLET_TOWN
    assert stack_at(ram).current.name == "get_starter"


def test_win_lab_rival_needs_both_the_event_and_a_winning_latch():
    ram = make_ram.battle()
    ram[S.IS_IN_BATTLE] = 0
    ram.event(S.EVENT_BATTLED_RIVAL_IN_OAKS_LAB)
    state = decode(bytes(ram))

    unset = BattleLatch()
    assert unset.result is None
    stack = GoalStack()
    stack.advance(state, unset)
    assert stack.current.name == "win_lab_rival"  # fails closed while the latch is unset

    lost = BattleLatch()
    lost.update(2, BattleLatch.LOSE)  # in a trainer battle
    lost.update(0, BattleLatch.LOSE)  # battle ends: latch fires
    stack = GoalStack()
    stack.advance(state, lost)
    assert stack.current.name == "win_lab_rival"

    won = BattleLatch()
    won.update(2, BattleLatch.WIN)
    won.update(0, BattleLatch.WIN)
    stack = GoalStack()
    stack.advance(state, won)
    assert stack.current.name == "reach_viridian"


def test_the_latch_fires_on_any_nonzero_to_zero_flip_and_holds():
    for previous in (1, 2, 0xFF):
        latch = BattleLatch()
        latch.update(previous, BattleLatch.WIN)
        assert latch.result is None  # nothing latched while the battle runs
        latch.update(0, BattleLatch.WIN)
        assert latch.result == BattleLatch.WIN and latch.count == 1
        latch.update(0, BattleLatch.LOSE)  # garbage in the slot afterwards is ignored
        assert latch.result == BattleLatch.WIN and latch.count == 1


def test_the_stack_never_regresses():
    stack = GoalStack()
    latch = BattleLatch()
    viridian = make_ram.bedroom()
    viridian[S.CUR_MAP] = S.VIRIDIAN_CITY
    stack.advance(decode(bytes(viridian)), latch)
    index = stack.index
    stack.advance(decode(bytes(make_ram.bedroom())), latch)  # back upstairs somehow
    assert stack.index == index


def test_every_goal_carries_a_sentence_for_the_state_field():
    assert all(g.sentence.endswith(".") and len(g.sentence) > 20 for g in GOALS)
