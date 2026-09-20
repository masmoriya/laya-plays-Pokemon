"""ROM-backed data for Gold/Silver '97 Reforged.

The hack keeps the Crystal engine but replaces the species table. Reading names from
the supplied ROM keeps the adapter tied to the cartridge the user is actually running
and avoids pretending that the standard Gold species list is authoritative.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


NAME_WIDTH = 10
SPECIES_COUNT = 253
STARTERS = ("CHIKORITA", "FLAMBEAR", "CRUIZE")
_ANCHOR = bytes((0x81, 0x94, 0x8B, 0x81, 0x80, 0x92, 0x80, 0x94, 0x91, 0x50))
_CHARS = {0x50: "@", 0x7F: " ", 0xE0: "'", 0xE3: "-", 0xE8: ".", 0xEF: "♂", 0xF5: "♀"}
_CHARS.update({0x80 + i: chr(65 + i) for i in range(26)})
_CHARS.update({0xA0 + i: chr(97 + i) for i in range(26)})
_GAME_CHARS = {0x50: " ", 0x7F: " ", 0x4E: " ", 0xE3: "-", 0xE8: ".",
               0xF4: ",", 0xEF: "♂", 0xF5: "♀"}
_GAME_CHARS[0x54] = "Poké"
_GAME_CHARS.update({0x80 + i: chr(65 + i) for i in range(26)})
_GAME_CHARS.update({0xA0 + i: chr(97 + i) for i in range(26)})
_BASE_STAT_ANCHOR = bytes((155, 45, 54, 50, 60, 60, 40))
_SEED_ENTRY = bytes((0x92, 0x84, 0x84, 0x83, 0x50))
_TYPE_NAMES = (
    "NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BIRD", "BUG",
    "DRAGON", "DARK", "STEEL", *("UNKNOWN",) * 10,
    "FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE", "GHOST",
)


def _decode_name(raw: bytes) -> str:
    chars = "".join(_CHARS.get(byte, "?") for byte in raw)
    return chars.split("@", 1)[0].strip() or "UNKNOWN"


def _flag_ids(mem, address: int, count: int) -> tuple[int, ...]:
    return tuple(
        species
        for species in range(1, count + 1)
        if mem[address + (species - 1) // 8] & (1 << ((species - 1) % 8))
    )


@dataclass(frozen=True)
class SpeciesData:
    types: tuple[str, ...]
    base_stats: tuple[int, int, int, int, int, int]
    category: str | None = None
    height: int | None = None
    weight: int | None = None
    entry: str | None = None


def _game_text(raw: bytes) -> str:
    # The cartridge hyphenates words at a line/page break. Join those syllables
    # for the wider dashboard text while retaining ordinary hyphens.
    raw = raw.replace(b"\xe3\x4e", b"").replace(b"\xe3\x50", b"")
    return " ".join("".join(_GAME_CHARS.get(byte, "") for byte in raw).split())


@dataclass(frozen=True)
class Gold97RomData:
    names: tuple[str, ...]
    table_offset: int
    rom: bytes

    @classmethod
    def from_path(cls, path: str | Path):
        return cls.from_bytes(Path(path).read_bytes())

    @classmethod
    def from_bytes(cls, rom: bytes):
        offset = rom.find(_ANCHOR)
        if offset < 0:
            raise ValueError("Gold 97 species table not found")
        names = tuple(
            _decode_name(rom[offset + (species - 1) * NAME_WIDTH : offset + species * NAME_WIDTH])
            for species in range(1, SPECIES_COUNT + 1)
        )
        # These four entries distinguish Reforged from standard Gold/Crystal.
        expected = {1: "BULBASAUR", 152: "CHIKORITA", 153: "PETAMOLE", 155: "FLAMBEAR", 158: "CRUIZE"}
        if any(names[index - 1] != value for index, value in expected.items()):
            raise ValueError("ROM has a different species table")
        return cls(("UNKNOWN", *names), offset, rom)

    def name(self, species_id: int) -> str:
        return self.names[species_id] if 0 < species_id < len(self.names) else f"MON_{species_id:02X}"

    def names_for(self, species_ids: tuple[int, ...]) -> tuple[str, ...]:
        return tuple(self.name(species_id) for species_id in species_ids)

    def pokedex_ids(self, mem, address: int) -> tuple[int, ...]:
        return _flag_ids(mem, address, SPECIES_COUNT)

    @lru_cache(maxsize=256)
    def trainer_name(self, trainer_class: int, trainer_id: int) -> str | None:
        """Resolve the current trainer from this ROM's class and party tables."""
        if not 1 <= trainer_class <= 100 or not 1 <= trainer_id <= 100:
            return None
        table = self._trainer_groups_offset()
        if table is None:
            return None
        bank_start = table // 0x4000 * 0x4000
        pointer = table + (trainer_class - 1) * 2
        if pointer + 2 > bank_start + 0x4000:
            return None
        address = int.from_bytes(self.rom[pointer:pointer + 2], "little")
        if not 0x4000 <= address < 0x8000:
            return None
        cursor = bank_start + address - 0x4000
        for _ in range(trainer_id - 1):
            end = self.rom.find(b"\xff", cursor, bank_start + 0x4000)
            if end < 0:
                return None
            cursor = end + 1
        name_end = self.rom.find(b"\x50", cursor, min(cursor + 20, bank_start + 0x4000))
        if name_end < cursor or not self.rom[cursor:name_end]:
            return None
        name = _game_text(self.rom[cursor:name_end]).title()
        class_name = self._trainer_class_name(trainer_class)
        return f"{class_name} {name}" if class_name else name

    @lru_cache(maxsize=1)
    def _trainer_groups_offset(self) -> int | None:
        def names(value):
            return bytes(0x80 + ord(char) - 65 for char in value) + b"\x50"
        falkner = self.rom.find(names("FALKNER"))
        whitney = self.rom.find(names("WHITNEY"))
        if falkner < 0 or whitney < 0 or falkner // 0x4000 != whitney // 0x4000:
            return None
        pointers = ((falkner % 0x4000 + 0x4000).to_bytes(2, "little")
                    + (whitney % 0x4000 + 0x4000).to_bytes(2, "little"))
        offset = self.rom.find(pointers)
        return offset if offset >= 0 and offset // 0x4000 == falkner // 0x4000 else None

    @lru_cache(maxsize=100)
    def _trainer_class_name(self, trainer_class: int) -> str | None:
        leader = bytes((0x8B, 0x84, 0x80, 0x83, 0x84, 0x91, 0x50))
        anchor = self.rom.find(leader * 7)
        if anchor < 0:
            return None
        cursor = anchor
        for _ in range(trainer_class - 1):
            end = self.rom.find(b"\x50", cursor, cursor + 30)
            if end < 0:
                return None
            cursor = end + 1
        end = self.rom.find(b"\x50", cursor, cursor + 30)
        if end < cursor:
            return None
        return _game_text(self.rom[cursor:end]).title()

    @lru_cache(maxsize=SPECIES_COUNT)
    def species_data(self, species_id: int) -> SpeciesData | None:
        """Read species facts from this exact cartridge, never a generic Pokédex."""
        if not 0 < species_id <= SPECIES_COUNT:
            return None
        stats = self._base_stats(species_id)
        entry = self._pokedex_entry(species_id)
        if stats is None and entry is None:
            return None
        return SpeciesData(
            types=stats[0] if stats else (),
            base_stats=stats[1] if stats else (),
            category=entry[0] if entry else None,
            height=entry[1] if entry else None,
            weight=entry[2] if entry else None,
            entry=entry[3] if entry else None,
        )

    def _base_stats(self, species_id: int):
        anchor = self.rom.find(_BASE_STAT_ANCHOR)
        table = anchor - 154 * 32 if anchor >= 0 else -1
        offset = table + (species_id - 1) * 32
        if table < 0 or offset < 0 or offset + 9 > len(self.rom):
            return None
        raw = self.rom[offset : offset + 9]
        values = tuple(raw[1:7])
        if raw[0] != species_id or not all(values) or raw[7] >= len(_TYPE_NAMES) or raw[8] >= len(_TYPE_NAMES):
            return None
        first, second = _TYPE_NAMES[raw[7]], _TYPE_NAMES[raw[8]]
        return ((first,) if first == second else (first, second), values)

    def _pokedex_entry(self, species_id: int):
        offsets = self._pokedex_offsets()
        if offsets is None or species_id > len(offsets):
            return None
        start = offsets[species_id - 1]
        name_end = self.rom.find(b"\x50", start, start + 24)
        if name_end < start or name_end + 5 >= len(self.rom):
            return None
        category = _game_text(self.rom[start:name_end])
        height = int.from_bytes(self.rom[name_end + 1:name_end + 3], "little")
        weight = int.from_bytes(self.rom[name_end + 3:name_end + 5], "little")
        next_start = offsets[species_id] if species_id < len(offsets) else len(self.rom)
        if not category or next_start <= name_end + 5:
            return None
        text = _game_text(self.rom[name_end + 5:next_start])
        return (category, height, weight, text or None)

    @lru_cache(maxsize=1)
    def _pokedex_offsets(self):
        """Locate the ordered entry bank by validating the cartridge's first entries.

        The hack does not publish stable ROM offsets. Its entry blocks are contiguous,
        so a verified Bulbasaur/ Ivysaur/ Venusaur seed-category sequence anchors the
        active ROM's table without assuming a stock Crystal layout.
        """
        starts = []
        search = 0
        while True:
            start = self.rom.find(_SEED_ENTRY, search)
            if start < 0:
                break
            starts.append(start)
            search = start + 1
        for start in starts:
            offsets, cursor = [], start
            for _ in range(SPECIES_COUNT):
                next_start = self._next_entry_start(cursor)
                if next_start is None:
                    offsets.append(cursor)
                    break
                offsets.append(cursor)
                cursor = next_start
            if len(offsets) >= 19 and self._entry_category_at(offsets[18]) == "RAT":
                return tuple(offsets)
        return None

    def _next_entry_start(self, start: int):
        limit = min(len(self.rom) - 8, start + 700)
        for candidate in range(start + 7, limit):
            if self.rom[candidate - 1] != 0x50:
                continue
            name_end = self.rom.find(b"\x50", candidate, candidate + 13)
            if not candidate < name_end <= candidate + 12:
                continue
            name = self.rom[candidate:name_end]
            if not all(byte == 0x7F or 0x80 <= byte <= 0x99 for byte in name):
                continue
            height = int.from_bytes(self.rom[name_end + 1:name_end + 3], "little")
            weight = int.from_bytes(self.rom[name_end + 3:name_end + 5], "little")
            if not 10 <= height <= 999 or not 1 <= weight <= 9999:
                continue
            if self.rom[name_end + 5] in _GAME_CHARS:
                return candidate
        return None

    def _entry_category_at(self, start: int) -> str:
        end = self.rom.find(b"\x50", start, start + 24)
        return _game_text(self.rom[start:end]) if end >= 0 else ""
