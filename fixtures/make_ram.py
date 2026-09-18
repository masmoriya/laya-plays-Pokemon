"""Build synthetic WRAM images for the decoder tests.

These are our own bytes poked at the documented addresses into a zero-filled 64 KB
address space, not a dump from a running ROM. The trade: a fixture can never catch a
wrong address, only a wrong reading of the right one. Run this file to regenerate
`fixtures/ram_*.bin`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jpp import symbols as S  # noqa: E402

HERE = Path(__file__).parent


class Ram(bytearray):
    """A 64 KB address space with the writers the fixtures need."""

    def __init__(self):
        super().__init__(0x10000)

    def u16be(self, addr, value):
        self[addr] = value >> 8
        self[addr + 1] = value & 0xFF

    def bcd(self, addr, length, value):
        digits = str(value).rjust(length * 2, "0")[-length * 2 :]
        for i in range(length):
            self[addr + i] = int(digits[2 * i]) << 4 | int(digits[2 * i + 1])

    def event(self, bit, on=True):
        addr, offset = S.event_address(bit)
        if on:
            self[addr] |= 1 << offset
        else:
            self[addr] &= ~(1 << offset) & 0xFF

    def mon(
        self, base, species, level, hp, max_hp, types, moves, pp, status=0, party=True
    ):
        o = S.P_SPECIES if party else S.B_SPECIES
        off = (
            (
                S.P_HP,
                S.P_STATUS,
                S.P_TYPE1,
                S.P_TYPE2,
                S.P_MOVES,
                S.P_PP,
                S.P_LEVEL,
                S.P_MAX_HP,
            )
            if party
            else (
                S.B_HP,
                S.B_STATUS,
                S.B_TYPE1,
                S.B_TYPE2,
                S.B_MOVES,
                S.B_PP,
                S.B_LEVEL,
                S.B_MAX_HP,
            )
        )
        hp_o, st_o, t1_o, t2_o, mv_o, pp_o, lv_o, mx_o = off
        self[base + o] = species
        self.u16be(base + hp_o, hp)
        self[base + st_o] = status
        self[base + t1_o], self[base + t2_o] = types
        for i, m in enumerate(moves):
            self[base + mv_o + i] = m
        for i, p in enumerate(pp):
            self[base + pp_o + i] = p
        self[base + lv_o] = level
        self.u16be(base + mx_o, max_hp)


# internal ids from gamedata; spelled out here so the fixtures read as data
CHARMANDER, SQUIRTLE, PIDGEY = 176, 177, 36
NORMAL, FIRE, WATER, FLYING = 0x00, 0x14, 0x15, 0x02
SCRATCH, EMBER, TACKLE, GROWL, TAIL_WHIP, GUST = 10, 52, 33, 45, 39, 16


def bedroom():
    """Start of the run: upstairs in Red's house, no party, no events."""
    r = Ram()
    r[S.CUR_MAP] = S.REDS_HOUSE_2F
    r[S.X_COORD], r[S.Y_COORD] = 3, 6
    r[S.PARTY_COUNT] = 0
    r.bcd(S.PLAYER_MONEY, 3, 3000)
    return r


def overworld():
    """Pallet Town with a starter in the party, walking to the lab."""
    r = Ram()
    r[S.CUR_MAP] = S.PALLET_TOWN
    r[S.X_COORD], r[S.Y_COORD] = 10, 8
    r[S.PARTY_COUNT] = 1
    r.mon(
        S.PARTY_MONS,
        CHARMANDER,
        5,
        19,
        19,
        (FIRE, FIRE),
        (SCRATCH, GROWL),
        (35, 40),
    )
    r.bcd(S.PLAYER_MONEY, 3, 3000)
    r.event(S.EVENT_GOT_STARTER)
    return r


# the four-turn rival battle: (active HP, opponent HP) per turn
RIVAL_TURNS = ((19, 21), (15, 14), (8, 17), (4, 6))


def battle(active_hp=8, foe_hp=17):
    """A turn of the lab rival battle. Defaults to turn 3, CONTEXT section 4's example."""
    r = overworld()
    r[S.CUR_MAP] = S.OAKS_LAB
    r[S.X_COORD], r[S.Y_COORD] = 5, 4
    r[S.IS_IN_BATTLE] = 2  # trainer
    r[S.PARTY_COUNT] = 2
    r.mon(
        S.PARTY_MONS,
        CHARMANDER,
        5,
        active_hp,
        19,
        (FIRE, FIRE),
        (SCRATCH, GROWL, EMBER),
        (33, 40, 25),
    )
    r.mon(
        S.PARTY_MONS + S.PARTY_STRUCT_LEN,
        PIDGEY,
        4,
        17,
        17,
        (NORMAL, FLYING),
        (TACKLE, GUST),
        (35, 35),
    )
    r.mon(
        S.BATTLE_MON,
        CHARMANDER,
        5,
        active_hp,
        19,
        (FIRE, FIRE),
        (SCRATCH, GROWL, EMBER),
        (33, 40, 25),
        party=False,
    )
    r.mon(
        S.ENEMY_MON,
        SQUIRTLE,
        5,
        foe_hp,
        21,
        (WATER, WATER),
        (TACKLE, TAIL_WHIP),
        (35, 30),
        party=False,
    )
    return r


def fainted_party():
    """Six members, one fainted and one asleep, for the party-decode edges."""
    r = Ram()
    r[S.CUR_MAP] = S.VIRIDIAN_CITY
    r[S.PARTY_COUNT] = 6
    for slot in range(6):
        base = S.PARTY_MONS + slot * S.PARTY_STRUCT_LEN
        hp = 0 if slot == 2 else 20 + slot
        r.mon(
            base,
            PIDGEY,
            5 + slot,
            hp,
            20 + slot,
            (NORMAL, FLYING),
            (TACKLE,),
            (35,),
            status=0b010 if slot == 4 else 0,
        )
    r.bcd(S.PLAYER_MONEY, 3, 129999)
    return r


def battle_turn(n):
    """Turn n (1-4) of the rival battle."""
    return battle(*RIVAL_TURNS[n - 1])


FIXTURES = {
    "ram_bedroom.bin": bedroom,
    "ram_overworld.bin": overworld,
    "ram_battle.bin": battle,
    "ram_party.bin": fainted_party,
}


def main():
    for name, build in FIXTURES.items():
        (HERE / name).write_bytes(bytes(build()))
        print(f"wrote fixtures/{name}")


if __name__ == "__main__":
    main()
