from types import SimpleNamespace

from jpp.battle_progress import BattleProgress


def _state(active, result=None, species="FLAMBEAR"):
    return SimpleNamespace(in_battle=active, battle_result=result,
                           battle=SimpleNamespace(opponent=SimpleNamespace(species=species)))


def test_completed_battles_count_once_and_unknown_results_do_not_invent_wins():
    tracker = BattleProgress()
    assert tracker.update(_state(True)) is None
    assert tracker.opponent == "FLAMBEAR"
    assert tracker.update(_state(False, 0)) == "win"
    assert tracker.update(_state(False, 0)) is None
    assert (tracker.battles, tracker.wins, tracker.losses) == (1, 1, 0)
    tracker.update(_state(True))
    assert tracker.update(_state(False, 255)) == "result unavailable"
    assert (tracker.battles, tracker.wins, tracker.losses) == (2, 1, 0)
    tracker.update(_state(True))
    assert tracker.update(_state(False, 1)) == "loss"
    assert (tracker.battles, tracker.wins, tracker.losses) == (3, 1, 1)
    tracker.update(_state(True))
    assert tracker.update(_state(False, 0x40)) == "win"  # captured Pokémon
    assert (tracker.battles, tracker.wins, tracker.losses) == (4, 2, 1)
