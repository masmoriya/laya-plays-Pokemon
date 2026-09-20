from pathlib import Path

from jpp.gold97_adapter import (
    BADGES,
    PARTY_COUNT,
    PARTY_SPECIES,
    PARTY_MONS,
    MAP_GROUP,
    MAP_NUMBER,
    X_COORD,
    Y_COORD,
    POKEDEX_CAUGHT,
    POKEDEX_SEEN,
    BATTLE_MODE,
    BATTLE_MON,
    ENEMY_MON,
    OTHER_TRAINER_CLASS,
    OTHER_TRAINER_ID,
    Gold97Adapter,
)
from jpp.gold97_data import NAME_WIDTH, Gold97RomData
from jpp.progress import ProgressTracker


def _rom(tmp_path: Path) -> Path:
    chars = {chr(65 + i): 0x80 + i for i in range(26)}
    chars["@"] = 0x50
    table = bytearray(b"\0" * (NAME_WIDTH * 253))
    names = {1: "BULBASAUR", 152: "CHIKORITA", 153: "PETAMOLE", 155: "FLAMBEAR", 158: "CRUIZE"}
    for species, name in names.items():
        table[(species - 1) * NAME_WIDTH : species * NAME_WIDTH] = bytes(
            chars[char] for char in (name + "@" * NAME_WIDTH)[:NAME_WIDTH]
        )
    path = tmp_path / "gold97.gbc"
    path.write_bytes(table)
    return path


def test_rom_table_reads_reforged_names(tmp_path):
    data = Gold97RomData.from_path(_rom(tmp_path))
    assert data.name(152) == "CHIKORITA"
    assert data.name(155) == "FLAMBEAR"
    assert data.name(158) == "CRUIZE"


def test_adapter_reads_party_badges_and_pokedex(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[PARTY_COUNT] = 1
    memory[PARTY_SPECIES] = 155
    memory[PARTY_MONS] = 155
    memory[PARTY_MONS + 31] = 5
    memory[PARTY_MONS + 34 : PARTY_MONS + 36] = b"\0\x14"
    memory[PARTY_MONS + 36 : PARTY_MONS + 38] = b"\0\x14"
    memory[BADGES] = 1
    memory[POKEDEX_CAUGHT + 19] = 1 << 2  # species 155
    memory[POKEDEX_SEEN + 18] = 1 << 7  # species 152
    snapshot = adapter.snapshot(type("Emulator", (), {"memory": memory})())
    state = snapshot.state
    assert state.party[0].species == "FLAMBEAR"
    assert state.badge_ids == ("johto_1",)
    assert state.pokedex_caught_ids == (155,)
    assert state.pokedex_seen_ids == (152,)
    progress = ProgressTracker().update(state).to_dict()
    assert (progress["pokedex_caught"], progress["pokedex_seen"], progress["pokedex_total"]) == (1, 1, 253)


def test_adapter_does_not_promote_uninitialized_party_or_map_ram(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[PARTY_COUNT] = 5
    state = adapter.snapshot(type("Emulator", (), {"memory": memory})()).state
    assert state.party == ()
    assert state.map_name == "MAP_UNAVAILABLE"
    assert state.x is None and state.y is None
    progress = ProgressTracker(map_history=["MAP_00_00"]).update(state).to_dict()
    assert progress["party"] == []
    assert progress["map_history"] == []


def test_adapter_uses_party_species_list_when_struct_header_lags(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[PARTY_COUNT] = 1
    memory[PARTY_SPECIES] = 155
    # The game writes the list before the struct's species byte while generating
    # the starter's stats; level and HP are already available in the struct.
    memory[PARTY_MONS + 31] = 5
    memory[PARTY_MONS + 34 : PARTY_MONS + 36] = b"\0\x14"
    memory[PARTY_MONS + 36 : PARTY_MONS + 38] = b"\0\x14"
    emulator = type("Emulator", (), {"memory": memory})()
    assert adapter.snapshot(emulator).state.party == ()
    state = adapter.snapshot(emulator).state
    assert state.party[0].species == "FLAMBEAR"


def test_adapter_reads_live_map_coordinates(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[MAP_GROUP] = 0x14
    memory[MAP_NUMBER] = 0x05
    memory[X_COORD] = 3
    memory[Y_COORD] = 5
    state = adapter.snapshot(type("Emulator", (), {"memory": memory})()).state
    assert (state.map_name, state.x, state.y) == ("MAP_14_05", 3, 5)
    assert ProgressTracker().update(state).to_dict()["map_history"] == ["MAP_14_05"]


def test_gold97_banked_reads_ignore_selected_wram_bank(tmp_path):
    class SwitchableMemory:
        def __init__(self):
            self.banks = {1: bytearray(0x10000), 3: bytearray(0x10000)}

        def __getitem__(self, key):
            bank, address = key if isinstance(key, tuple) else (3, key)
            return self.banks[bank][address]

    memory = SwitchableMemory()
    good = memory.banks[1]
    good[PARTY_COUNT] = 1
    good[PARTY_SPECIES] = 155
    good[PARTY_MONS] = 155
    good[PARTY_MONS + 31] = 5
    good[PARTY_MONS + 34:PARTY_MONS + 38] = b"\0\x14\0\x14"
    memory.banks[3][PARTY_COUNT] = 1
    memory.banks[3][PARTY_SPECIES] = 127  # never substitute a different species
    state = Gold97Adapter(_rom(tmp_path)).snapshot(type("Emulator", (), {"memory": memory})()).state
    assert state.party[0].species == "FLAMBEAR"


def test_party_transition_does_not_promote_ghost_species(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[PARTY_COUNT] = 1
    memory[PARTY_SPECIES] = memory[PARTY_MONS] = 155
    memory[PARTY_MONS + 31] = 5
    memory[PARTY_MONS + 34:PARTY_MONS + 38] = b"\0\x14\0\x14"
    emulator = type("Emulator", (), {"memory": memory})()
    assert adapter.snapshot(emulator).state.party[0].species == "FLAMBEAR"
    memory[PARTY_SPECIES] = 152
    assert adapter.snapshot(emulator).state.party[0].species == "FLAMBEAR"
    memory[PARTY_MONS] = 152
    assert adapter.snapshot(emulator).state.party[0].species == "CHIKORITA"


def test_held_item_and_battle_moves_pp_are_decoded(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[PARTY_COUNT] = 1
    memory[PARTY_SPECIES] = memory[PARTY_MONS] = 155
    memory[PARTY_MONS + 1] = 18  # Potion
    memory[PARTY_MONS + 2] = 33  # Tackle
    memory[PARTY_MONS + 23] = 35
    memory[PARTY_MONS + 31] = 5
    memory[PARTY_MONS + 34:PARTY_MONS + 38] = b"\0\x14\0\x14"
    memory[BATTLE_MODE] = 1
    memory[BATTLE_MON] = 155
    memory[BATTLE_MON + 2] = 33
    memory[BATTLE_MON + 8] = 0xC0 | 12
    memory[BATTLE_MON + 13] = 5
    memory[BATTLE_MON + 16:BATTLE_MON + 20] = b"\0\x14\0\x14"
    memory[ENEMY_MON] = 1
    state = adapter.snapshot(type("Emulator", (), {"memory": memory})()).state
    assert state.party[0].held_item == "Potion"
    assert state.party[0].moves == ("Tackle",)
    assert state.battle.active.pp == (12,)


def test_move_pp_keeps_its_slot_and_incomplete_opponents_stay_unknown(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[BATTLE_MODE] = 2
    memory[BATTLE_MON] = 155
    memory[BATTLE_MON + 4] = 33  # third move, not first
    memory[BATTLE_MON + 10] = 7
    memory[BATTLE_MON + 13] = 5
    memory[BATTLE_MON + 16:BATTLE_MON + 20] = b"\0\x14\0\x14"
    memory[ENEMY_MON] = 1  # species written before level and health
    state = adapter.snapshot(type("Emulator", (), {"memory": memory})()).state
    assert state.battle.active.moves == ("Tackle",)
    assert state.battle.active.pp == (7,)
    assert state.battle.opponent is None
    assert state.opponent_label == "Trainer"


def test_adapter_reads_actual_trainer_identity_and_deduplicates_monotype(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[BATTLE_MODE] = 2
    memory[OTHER_TRAINER_CLASS] = 0x3B
    memory[OTHER_TRAINER_ID] = 1
    memory[BATTLE_MON] = 155
    memory[BATTLE_MON + 13] = 5
    memory[BATTLE_MON + 16:BATTLE_MON + 20] = b"\0\x14\0\x14"
    memory[BATTLE_MON + 30] = memory[BATTLE_MON + 31] = 21
    state = adapter.snapshot(type("Emulator", (), {"memory": memory})()).state
    assert state.opponent_label == "Pokéfan Colette"
    assert state.battle.active.types == ("FIRE",)


def test_loading_another_timeline_drops_previous_party_fallback(tmp_path):
    adapter = Gold97Adapter(_rom(tmp_path))
    memory = bytearray(0x10000)
    memory[PARTY_COUNT] = 1
    memory[PARTY_SPECIES] = memory[PARTY_MONS] = 155
    memory[PARTY_MONS + 31] = 5
    memory[PARTY_MONS + 34:PARTY_MONS + 38] = b"\0\x14\0\x14"
    emulator = type("Emulator", (), {"memory": memory})()
    assert adapter.snapshot(emulator).state.party
    adapter.reset_transition()
    memory[PARTY_SPECIES] = 152
    assert adapter.snapshot(emulator).state.party == ()
