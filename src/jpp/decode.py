"""WRAM bytes in, a typed snapshot out.

`decode(mem)` takes anything indexable by absolute Game Boy address and returning a byte,
which is what `pyboy.memory` is and what `fixtures/make_ram.py` builds. Nothing here
touches PyBoy, so the whole decoder is testable against a synthetic RAM image.
"""

from dataclasses import dataclass, field

from . import gamedata, symbols as S


@dataclass(frozen=True)
class Mon:
    slot: int  # 1-6 for party members, 0 for the active battle mon or the opponent
    species: str
    level: int
    hp: int
    max_hp: int
    status: str
    types: tuple[str, ...]
    moves: tuple[str, ...] = ()
    pp: tuple[int, ...] = ()
    held_item: str | None = None
    species_id: int | None = None
    species_data: object | None = None

    @property
    def fainted(self) -> bool:
        return self.hp == 0

    @property
    def hp_fraction(self) -> float:
        return round(self.hp / self.max_hp, 2) if self.max_hp else 0.0


@dataclass(frozen=True)
class Battle:
    kind: str  # none, wild, trainer, lost
    active: Mon | None
    opponent: Mon | None


@dataclass(frozen=True)
class GameState:
    map_id: int
    map_name: str
    x: int
    y: int
    party: tuple[Mon, ...]
    badges: int
    money: int
    battle: Battle
    menu_item: int
    max_menu_item: int
    battle_menu_item: int  # where the FIGHT/PKMN/ITEM/RUN cursor was left
    move_list_index: int  # where the move cursor was left
    party_menu_item: int  # where the party cursor was left
    active_slot: int  # party index of the mon in battle, 0-based
    text_box_id: int
    joy_ignore: int
    walk_counter: int
    font_loaded: int
    tile_in_front: int
    events: bytes = field(repr=False, default=b"")

    def event(self, bit: int) -> bool:
        addr, offset = S.event_address(bit)
        index = addr - S.EVENT_FLAGS
        return (
            bool(self.events[index] >> offset & 1)
            if index < len(self.events)
            else False
        )

    @property
    def in_battle(self) -> bool:
        return self.battle.kind in ("wild", "trainer")


BATTLE_KINDS = {0: "none", 1: "wild", 2: "trainer", 0xFF: "lost"}


def _u16be(mem, addr: int) -> int:
    # Gen 1 stores HP and stats high byte first
    return mem[addr] * 256 + mem[addr + 1]


def _status(byte: int) -> str:
    if byte & 0b111:
        return "sleep"
    for bit, name in S.STATUS_NAMES:
        if byte >> bit & 1:
            return name
    return "none"


def _types(t1: int, t2: int) -> tuple[str, ...]:
    a, b = gamedata.type_name(t1), gamedata.type_name(t2)
    return (a,) if t1 == t2 else (a, b)


def _bcd(mem, addr: int, length: int) -> int:
    out = 0
    for i in range(length):
        byte = mem[addr + i]
        out = out * 100 + (byte >> 4) * 10 + (byte & 0xF)
    return out


def _battle_mon(mem, base: int, slot: int) -> Mon:
    moves = tuple(
        gamedata.move(mem[base + S.B_MOVES + i])[0]
        for i in range(4)
        if mem[base + S.B_MOVES + i]
    )
    return Mon(
        slot=slot,
        species=gamedata.species_name(mem[base + S.B_SPECIES]),
        level=mem[base + S.B_LEVEL],
        hp=_u16be(mem, base + S.B_HP),
        max_hp=_u16be(mem, base + S.B_MAX_HP),
        status=_status(mem[base + S.B_STATUS]),
        types=_types(mem[base + S.B_TYPE1], mem[base + S.B_TYPE2]),
        moves=moves,
        pp=tuple(mem[base + S.B_PP + i] & 0x3F for i in range(len(moves))),
    )


def _party_mon(mem, slot: int) -> Mon:
    base = S.PARTY_MONS + (slot - 1) * S.PARTY_STRUCT_LEN
    moves = tuple(
        gamedata.move(mem[base + S.P_MOVES + i])[0]
        for i in range(4)
        if mem[base + S.P_MOVES + i]
    )
    return Mon(
        slot=slot,
        species=gamedata.species_name(mem[base + S.P_SPECIES]),
        level=mem[base + S.P_LEVEL],
        hp=_u16be(mem, base + S.P_HP),
        max_hp=_u16be(mem, base + S.P_MAX_HP),
        status=_status(mem[base + S.P_STATUS]),
        types=_types(mem[base + S.P_TYPE1], mem[base + S.P_TYPE2]),
        moves=moves,
        # the top two bits of a PP byte hold PP Up count, so mask them off
        pp=tuple(mem[base + S.P_PP + i] & 0x3F for i in range(len(moves))),
    )


def decode(mem) -> GameState:
    map_id = mem[S.CUR_MAP]
    kind = BATTLE_KINDS.get(mem[S.IS_IN_BATTLE], "none")
    active = opponent = None
    if kind in ("wild", "trainer"):
        active = _battle_mon(mem, S.BATTLE_MON, 0)
        opponent = _battle_mon(mem, S.ENEMY_MON, 0)
    count = min(mem[S.PARTY_COUNT], 6)
    return GameState(
        map_id=map_id,
        map_name=S.MAP_NAMES.get(map_id, f"MAP_{map_id:02X}"),
        x=mem[S.X_COORD],
        y=mem[S.Y_COORD],
        party=tuple(_party_mon(mem, slot) for slot in range(1, count + 1)),
        badges=mem[S.OBTAINED_BADGES],
        money=_bcd(mem, S.PLAYER_MONEY, 3),
        battle=Battle(kind=kind, active=active, opponent=opponent),
        menu_item=mem[S.CURRENT_MENU_ITEM],
        max_menu_item=mem[S.MAX_MENU_ITEM],
        battle_menu_item=mem[S.BATTLE_SAVED_MENU_ITEM],
        move_list_index=mem[S.PLAYER_MOVE_LIST_INDEX],
        party_menu_item=mem[S.PARTY_SAVED_MENU_ITEM],
        active_slot=mem[S.PLAYER_MON_NUMBER],
        text_box_id=mem[S.TEXT_BOX_ID],
        joy_ignore=mem[S.JOY_IGNORE],
        walk_counter=mem[S.WALK_COUNTER],
        font_loaded=mem[S.FONT_LOADED],
        tile_in_front=mem[S.TILE_IN_FRONT],
        events=bytes(mem[S.EVENT_FLAGS + i] for i in range(S.EVENT_FLAGS_LEN)),
    )
