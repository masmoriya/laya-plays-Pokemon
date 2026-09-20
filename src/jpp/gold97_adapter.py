"""Memory adapter for the Gold/Silver '97 Reforged Crystal build."""

from dataclasses import dataclass
from types import SimpleNamespace

from .decode import Battle, Mon
from .gold97_data import Gold97RomData
from .gold97_catalog import map_details, item_name, move_name


# Gold 97 Reforged adds five bytes before the Crystal map/party block. These
# are the cartridge's live addresses, not the offsets from an unmodified ROM.
PARTY_COUNT = 0xDCDC
PARTY_SPECIES = 0xDCDD
PARTY_MONS = 0xDCE4
PARTY_STRUCT_LEN = 0x30
POKEDEX_CAUGHT = 0xDE9E
POKEDEX_SEEN = 0xDEBE
BADGES = 0xD857
MAP_GROUP = 0xDCBA
MAP_NUMBER = 0xDCBB
Y_COORD = 0xDCBC
X_COORD = 0xDCBD
BATTLE_MON = 0xC62C
ENEMY_MON = 0xD206
BATTLE_MODE = 0xD22D
BATTLE_RESULT = 0xD0F3
OTHER_TRAINER_CLASS = 0xD22F
OTHER_TRAINER_ID = 0xD231

_TYPE_NAMES = (
    "NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BIRD", "BUG",
    "DRAGON", "DARK", "STEEL", *("UNKNOWN",) * 10,
    "FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE", "GHOST",
)


def _u16(mem, address: int) -> int:
    return (mem[address] << 8) | mem[address + 1]


def _types(*identifiers):
    values = tuple(_TYPE_NAMES[value] if value < len(_TYPE_NAMES) else "UNKNOWN" for value in identifiers)
    return tuple(dict.fromkeys(values))


class Gold97Memory:
    """Pin the hack's WRAMX game data to bank 1, independent of LCD/game state."""

    def __init__(self, memory):
        self.memory = memory

    def __getitem__(self, address):
        if 0xD000 <= address < 0xE000:
            try:
                return self.memory[1, address]
            except TypeError:  # plain byte arrays used by the decoder tests
                pass
        return self.memory[address]


@dataclass(frozen=True)
class Gold97State:
    map_group: int
    map_number: int
    x: int | None
    y: int | None
    map_name: str
    party: tuple[Mon, ...]
    battle: Battle
    badge_ids: tuple[str, ...]
    badge_total: int
    pokedex_caught_ids: tuple[int, ...]
    pokedex_seen_ids: tuple[int, ...]
    pokedex_species: tuple[str, ...]
    area_name: str = ""
    locality: str = ""
    map_width: int = 0
    map_height: int = 0
    battle_result: int | None = None
    opponent_label: str | None = None

    @property
    def in_battle(self) -> bool:
        return self.battle.kind in ("wild", "trainer")


class Gold97Adapter:
    title = "GOLD 97 REFORGED"
    supports_ram_progress = True

    def __init__(self, path, data=None):
        self.data = data or Gold97RomData.from_path(path)
        self._last_party: tuple[Mon, ...] = ()
        self._pending_starter = None

    def reset_transition(self):
        """Drop the preceding timeline's party when a different state is loaded."""
        self._last_party = ()
        self._pending_starter = None

    def _mon(self, mem, base: int, slot: int, battle=False, species_id=None) -> Mon:
        species = mem[base] if species_id is None else species_id
        if battle:
            level, status, hp, max_hp = mem[base + 13], mem[base + 14], _u16(mem, base + 16), _u16(mem, base + 18)
            types = _types(*(mem[base + offset] for offset in (30, 31)))
            indices = tuple(i for i in range(4) if mem[base + 2 + i])
            moves = tuple(move_name(mem[base + 2 + i]) for i in indices)
            pp = tuple(mem[base + 8 + i] & 0x3f for i in indices)
        else:
            level, status, hp, max_hp = mem[base + 31], mem[base + 32], _u16(mem, base + 34), _u16(mem, base + 36)
            types = ("UNKNOWN",)
            indices = tuple(i for i in range(4) if mem[base + 2 + i])
            moves = tuple(move_name(mem[base + 2 + i]) for i in indices)
            pp = tuple(mem[base + 23 + i] & 0x3f for i in indices)
        return Mon(slot=slot, species=self.data.name(species), level=level, hp=hp, max_hp=max_hp,
                   status="status" if status else "none", types=types, moves=moves, pp=pp,
                   held_item=item_name(mem[base + 1]) if not battle else None,
                   species_id=species, species_data=self.data.species_data(species))

    def snapshot(self, emulator):
        mem = Gold97Memory(emulator.memory)
        count = mem[PARTY_COUNT]
        party = []
        # The party list is the authoritative membership record.  The struct's
        # first byte can briefly lag while the game finishes generating stats,
        # which used to make a newly obtained starter disappear from the HUD.
        species_ids = []
        for slot in range(min(count, 6)):
            species_id = mem[PARTY_SPECIES + slot]
            if not (0 < species_id < len(self.data.names)):
                break
            species_ids.append(species_id)
        for slot, species_id in enumerate(species_ids):
            base = PARTY_MONS + slot * PARTY_STRUCT_LEN
            mon = self._mon(mem, base, slot + 1, species_id=species_id)
            struct_species = mem[base]
            warming_first_starter = not self._last_party and count == 1 and slot == 0
            if warming_first_starter and struct_species == 0:
                candidate = (species_id, mon.level, mon.hp, mon.max_hp)
                if self._pending_starter != candidate:
                    self._pending_starter = candidate
                    break
            else:
                self._pending_starter = None
            if (struct_species != species_id and not (warming_first_starter and struct_species == 0)
                    or not 1 <= mon.level <= 100
                    or not 0 < mon.max_hp <= 999 or not 0 <= mon.hp <= mon.max_hp):
                break
            party.append(mon)
        # A party write can span frames. Keep only previously confirmed slots while
        # catching up; never promote a random WRAM byte into a new Pokémon.
        if count == 0:
            self._last_party = ()
            self._pending_starter = None
        elif count > 6 or len(party) != count:
            party = list(self._last_party)
        else:
            self._last_party = tuple(party)
        mode = mem[BATTLE_MODE]
        kind = {1: "wild", 2: "trainer"}.get(mode, "none")
        def battle_mon(address):
            species_id = mem[address]
            if not 0 < species_id < len(self.data.names):
                return None
            mon = self._mon(mem, address, 0, True)
            if not 1 <= mon.level <= 100 or not 0 < mon.max_hp <= 999:
                return None
            return mon

        battle = Battle(kind, battle_mon(BATTLE_MON) if kind != "none" else None,
                        battle_mon(ENEMY_MON) if kind != "none" else None)
        badges = tuple(
            f"johto_{index + 1}"
            for index in range(8)
            if mem[BADGES + index // 8] & (1 << (index % 8))
        )
        caught = self.data.pokedex_ids(mem, POKEDEX_CAUGHT)
        seen = self.data.pokedex_ids(mem, POKEDEX_SEEN)
        group, number = mem[MAP_GROUP], mem[MAP_NUMBER]
        map_ready = bool(group or number)
        label, locality, width, height = map_details(group, number)
        state = Gold97State(
            group,
            number,
            mem[X_COORD] if map_ready else None,
            mem[Y_COORD] if map_ready else None,
            f"MAP_{group:02X}_{number:02X}" if map_ready else "MAP_UNAVAILABLE",
            tuple(party),
            battle,
            badges, 8, caught, seen, self.data.names,
            label, locality, width, height,
            mem[BATTLE_RESULT] if kind == "none" else None,
            self._opponent_label(mem, kind),
        )
        return SimpleNamespace(
            state=state, badge_update=None, title=self.title, supports_ram_progress=True
        )

    def _opponent_label(self, mem, kind):
        if kind == "wild":
            return "Wild"
        if kind != "trainer":
            return None
        key = (mem[OTHER_TRAINER_CLASS], mem[OTHER_TRAINER_ID])
        return self.data.trainer_name(*key) or "Trainer"
