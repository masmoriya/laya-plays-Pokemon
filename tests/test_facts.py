from jpp import facts
from jpp.decode import decode


def test_type_multiplier_stacks_over_both_defender_types():
    assert facts.type_multiplier("FIRE", ("WATER",)) == 0.5
    assert facts.type_multiplier("WATER", ("FIRE",)) == 2.0
    assert facts.type_multiplier("NORMAL", ("GHOST",)) == 0.0
    assert facts.type_multiplier("ELECTRIC", ("WATER", "FLYING")) == 4.0
    assert facts.type_multiplier("NORMAL", ("WATER",)) == 1.0


def test_effectiveness_words_never_hand_over_a_number():
    for types, word in ((("WATER",), "not very effective"), (("GRASS",), "super effective")):
        line = facts.describe_move("EMBER", 25, types)
        assert word in line
        assert "0.5" not in line and "2.0" not in line


def test_move_description_carries_pp_and_type(battle_ram):
    active = decode(battle_ram).battle.active
    line = facts.describe_move("EMBER", 25, ("WATER",))
    assert line == (
        "attack with EMBER, a Fire move, 25 of 25 PP left, not very effective against WATER"
    )
    assert active.pp[0] == 33  # PP Up bits masked off


def test_hp_words_bucket_the_fraction():
    assert facts.hp_word(0.0) == "fainted"
    assert facts.hp_word(0.15) == "critical"
    assert facts.hp_word(0.42) == "hurt"
    assert facts.hp_word(1.0) == "healthy"


def test_battle_summary_is_trimmed(battle_ram):
    summary = facts.battle_summary(decode(battle_ram).battle.active)
    assert set(summary) == {"species", "level", "hp_fraction", "condition", "status", "types"}
