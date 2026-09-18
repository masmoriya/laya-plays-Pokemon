from conftest import load_ram

from jpp import symbols as S
from jpp.decode import decode

import make_ram


def test_bedroom_is_where_the_run_starts():
    st = decode(load_ram("ram_bedroom.bin"))
    assert (st.map_id, st.map_name) == (S.REDS_HOUSE_2F, "REDS_HOUSE_2F")
    assert st.party == ()
    assert st.battle.kind == "none"
    assert st.money == 3000
    assert not st.event(S.EVENT_GOT_STARTER)


def test_one_party_member_and_an_event_bit(overworld_ram):
    st = decode(overworld_ram)
    assert len(st.party) == 1
    mon = st.party[0]
    assert (mon.species, mon.level, mon.hp, mon.max_hp) == ("CHARMANDER", 5, 19, 19)
    assert mon.types == ("FIRE",)
    assert mon.moves == ("SCRATCH", "GROWL")
    assert mon.pp == (35, 40)
    assert st.event(S.EVENT_GOT_STARTER)
    assert not st.event(S.EVENT_BATTLED_RIVAL_IN_OAKS_LAB)


def test_full_party_with_a_faint_and_a_sleeper():
    st = decode(load_ram("ram_party.bin"))
    assert len(st.party) == 6
    assert st.party[2].fainted and st.party[2].hp_fraction == 0.0
    assert st.party[4].status == "sleep"
    assert [m.level for m in st.party] == [5, 6, 7, 8, 9, 10]
    assert st.money == 129999  # BCD across three bytes


def test_battle_block(battle_ram):
    st = decode(battle_ram)
    assert st.battle.kind == "trainer" and st.in_battle
    active, foe = st.battle.active, st.battle.opponent
    assert (active.species, active.hp, active.max_hp) == ("CHARMANDER", 8, 19)
    assert active.hp_fraction == 0.42
    assert active.moves == ("SCRATCH", "GROWL", "EMBER")
    assert active.pp == (33, 40, 25)
    assert (foe.species, foe.level, foe.types) == ("SQUIRTLE", 5, ("WATER",))
    assert foe.hp_fraction == 0.81


def test_is_in_battle_sentinels():
    ram = make_ram.overworld()
    for byte, kind in ((0, "none"), (1, "wild"), (2, "trainer"), (0xFF, "lost")):
        ram[S.IS_IN_BATTLE] = byte
        st = decode(bytes(ram))
        assert st.battle.kind == kind
        assert st.in_battle == (kind in ("wild", "trainer"))
        # only a live battle decodes the battle-struct blocks
        assert (st.battle.active is not None) == st.in_battle


def test_event_bit_indexing_matches_the_constant_order():
    ram = make_ram.bedroom()
    ram.event(S.EVENT_BATTLED_RIVAL_IN_OAKS_LAB)
    st = decode(bytes(ram))
    assert st.event(S.EVENT_BATTLED_RIVAL_IN_OAKS_LAB)
    assert not st.event(S.EVENT_GOT_STARTER)  # the neighbouring bit stays clear
    # bit 35 is byte 4, bit 3 of wEventFlags
    assert st.events[4] == 0b1000


def test_party_count_is_clamped():
    ram = make_ram.overworld()
    ram[S.PARTY_COUNT] = 200
    assert len(decode(bytes(ram)).party) == 6
