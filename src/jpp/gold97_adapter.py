"""Memory adapter for the Gold/Silver '97 Reforged Crystal build."""

from dataclasses import dataclass, replace
from types import SimpleNamespace

from .decode import Battle, Mon
from .agent.gold97_mechanics import compatible
from .gold97_battle_state import decode_mon, battle_restrictions
from .gold97_data import Gold97RomData, _decode_name
from .gold97_catalog import map_details
from .gold97_movement import player_destination
from .agent.gold97_screen import battle_menu, cursor_cell, visible_rows, _party_cursor


# Gold 97 Reforged adds five bytes before the Crystal map/party block. These
# are the cartridge's live addresses, not the offsets from an unmodified ROM.
PARTY_COUNT = 0xDCDC
PARTY_SPECIES = 0xDCDD
PARTY_MONS = 0xDCE4
PARTY_STRUCT_LEN = 0x30
EGG_ID = 0xFE
POKEDEX_CAUGHT = 0xDE9E
POKEDEX_SEEN = 0xDEBE
BADGES = 0xD857
MAP_GROUP = 0xDCBA
MAP_NUMBER = 0xDCBB
Y_COORD = 0xDCBC
X_COORD = 0xDCBD
CUR_BATTLE_MON = 0xD0D4
BATTLE_MON = 0xC62C
ENEMY_MON = 0xD206
BATTLE_MODE = 0xD22D
BATTLE_RESULT = 0xD0EE  # battle scratch RAM does not share the party block shift
MENU_CURSOR_Y = 0xCFA9
MENU_CURSOR_X = 0xCFAA
OTHER_TRAINER_CLASS = 0xD22F
OTHER_TRAINER_ID = 0xD231
# Verified against the v6.1c cartridge's opening sequence. These are game
# progress bytes, not rewards inferred from the rendered screen.
READ_OAKS_EMAIL = 0xDAE4
# wEventFlags begins at DA72; EVENT_TALKED_TO_KURT_AND_FALKNER is bit 268.
KURT_FALKNER_EVENT_BYTE = 0xDA93
KURT_FALKNER_EVENT_MASK = 0x10
# Pinned event_flags.asm: EVENT_GOT_HM01_CUT is bit 16 of wEventFlags.
# BillsFamilysHouse.asm sets it after the HM gift; only decode the exact build.
GOT_CUT_EVENT_BYTE = 0xDA74
GOT_CUT_EVENT_MASK = 0x01
# Pinned event_flags.asm: EVENT_ROUTE36_TREE_CHOPPED is bit 270. Route102.asm
# sets it only after the Cut-gated gardener clears the Route 102 obstruction.
ROUTE_102_TREE_CHOPPED_EVENT_BYTE = 0xDA93
ROUTE_102_TREE_CHOPPED_EVENT_MASK = 0x40
# Route102.asm sets EVENT_ROUTE_102_SILVER after the scripted rival sequence.
ROUTE_102_RIVAL_EVENT_BYTE = 0xDAAE
ROUTE_102_RIVAL_EVENT_MASK = 0x80
OPENING_SCENE = {3: 0xD986, 4: 0xD987, 5: 0xD988,
                 6: 0xD989, 7: 0xD98A}
NUM_ITEMS = 0xD892
ITEMS = 0xD893
POTION_ID = 0x12
MONEY = 0xD84E
NUM_BALLS = 0xD8D7
BALLS = 0xD8D8
POKE_BALL_ID = 0x05
LAST_SPAWN_MAP_GROUP = 0xDCB7
LAST_SPAWN_MAP_NUMBER = 0xDCB8

def _u24(mem, address: int) -> int:
    """Crystal stores money as a big-endian binary quantity, not BCD."""
    return (mem[address] << 16) | (mem[address + 1] << 8) | mem[address + 2]


def _inventory_quantity(mem, address: int, count_address: int, item_id: int) -> int:
    """Read the dedicated Gen 2 ball pocket without treating empty bytes as items."""
    count = min(mem[count_address], 12)
    for slot in range(count):
        if mem[address + slot * 2] == item_id:
            return mem[address + slot * 2 + 1]
    return 0


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
    opponent_trainer_class: int | None = None
    read_oaks_email: bool = False
    opening_scene: int | None = None
    battle_menu_cursor: tuple[int, int] | None = None
    potion_slot: int | None = None
    potion_count: int = 0
    talked_to_kurt_and_falkner: bool = False
    money: int | None = None
    poke_ball_count: int | None = None
    battle_menu_kind: str | None = None
    screen_lines: tuple[str, ...] = ()
    last_spawn_map: tuple[int, int] | None = None
    screen_cursor: tuple[int, int] | None = None

    active_slot: int | None = None  # zero-based, validated against party
    mechanics_verified: bool = False
    upcoming_opponent: Mon | None = None
    received_cut_from_bill: bool = False
    route_102_tree_chopped: bool = False
    route_102_rival_complete: bool = False
    map_exits: tuple = ()
    frame_number: int = 0
    box_roster: tuple = ()
    storage_verified: bool = False
    current_box: int | None = None
    party_cursor: int | None = None
    pc_selection: int | None = None
    box_names: tuple = ()
    battle_participants: int | None = None
    overworld_objects: tuple | None = None
    player_facing: str | None = None
    player_moving: bool = False
    player_next_position: tuple[int, int] | None = None
    route_103_slowpoke_cleared: bool | None = None
    story_milestones: tuple[int, ...] = ()
    escape_allowed: bool | None = None
    switch_allowed: bool | None = None
    owned_hms: tuple[str, ...] = ()
    strength_active: bool | None = None

    @property
    def in_battle(self) -> bool:
        return self.battle.kind in ("wild", "trainer")


class Gold97Adapter:
    title = "GOLD 97 REFORGED"
    supports_ram_progress = True

    def __init__(self, path, data=None):
        self.data = data or Gold97RomData.from_path(path)
        self.mechanics_verified = compatible(self.data.rom)
        self._last_party: tuple[Mon, ...] = ()
        self._pending_starter = None

    def reset_transition(self):
        """Drop the preceding timeline's party when a different state is loaded."""
        self._last_party = ()
        self._storage = ((), False, None)
        self._pending_starter = None

    def _mon(self, mem, base, slot, battle=False, species_id=None):
        mon = decode_mon(self.data, mem, base, slot, battle, species_id,
                         self.mechanics_verified)
        if not battle and species_id == EGG_ID:
            # The party species list uses the EGG sentinel while the struct
            # intentionally retains the species that will hatch.  Keep the
            # slot so cartridge indices remain aligned, but never expose the
            # egg as a usable battler.
            return replace(mon, species="EGG", hp=0, status="none", types=(),
                           moves=(), pp=(), max_pp=(), stats=(), species_data=None)
        return mon

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
            if species_id != EGG_ID and not (0 < species_id < len(self.data.names)):
                break
            species_ids.append(species_id)
        for slot, species_id in enumerate(species_ids):
            base = PARTY_MONS + slot * PARTY_STRUCT_LEN
            mon = self._mon(mem, base, slot + 1, species_id=species_id)
            struct_species = mem[base]
            species_matches = (struct_species == species_id or
                               species_id == EGG_ID and
                               0 < struct_species < len(self.data.names))
            warming_first_starter = not self._last_party and count == 1 and slot == 0
            if warming_first_starter and struct_species == 0:
                candidate = (species_id, mon.level, mon.hp, mon.max_hp)
                if self._pending_starter != candidate:
                    self._pending_starter = candidate
                    break
            else:
                self._pending_starter = None
            if (not species_matches and not (warming_first_starter and struct_species == 0)
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
        screen_lines, screen_tiles = visible_rows(mem)
        menu_kind, visible_cursor = battle_menu(screen_lines, screen_tiles)
        legacy_cursor = ((mem[MENU_CURSOR_X], mem[MENU_CURSOR_Y])
                         if mem[MENU_CURSOR_X] in (1, 2)
                         and 1 <= mem[MENU_CURSOR_Y] <= 4 else None)
        cursor = (visible_cursor if menu_kind else legacy_cursor) if kind != "none" else None
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
        potion_slot = next((slot for slot in range(min(mem[NUM_ITEMS], 20))
                            if mem[ITEMS + slot * 2] == POTION_ID), None)
        money = _u24(mem, MONEY)
        ball_count = _inventory_quantity(mem, BALLS, NUM_BALLS, POKE_BALL_ID)
        from .gold97_world import active_objects
        from .gold97_exits import map_exits
        from .gold97_story import story_milestones
        from .field_moves import HM_NAMES
        from .gold97_storage import storage
        # SRAM is sampled only outside battles; cache the stable roster during combat.
        if self.mechanics_verified and kind == 'none':
            self._storage = storage(self.data, emulator.memory)
        boxes, storage_ok, current_box = getattr(self, '_storage', ((), False, None))
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
            mem[OTHER_TRAINER_CLASS] if kind == "trainer" else None,
            bool(mem[READ_OAKS_EMAIL] & 0x20),
            mem[OPENING_SCENE[number]] if group == 20 and number in OPENING_SCENE else None,
            cursor,
            potion_slot,
            mem[ITEMS + potion_slot * 2 + 1] if potion_slot is not None else 0,
            bool(mem[KURT_FALKNER_EVENT_BYTE] & KURT_FALKNER_EVENT_MASK),
            money,
            ball_count,
            menu_kind if kind != "none" else None,
            screen_lines,
            ((mem[LAST_SPAWN_MAP_GROUP], mem[LAST_SPAWN_MAP_NUMBER])
             if mem[LAST_SPAWN_MAP_GROUP] or mem[LAST_SPAWN_MAP_NUMBER] else None),
            cursor_cell(screen_tiles),
            (mem[CUR_BATTLE_MON] if self.mechanics_verified and battle.active
             and mem[CUR_BATTLE_MON] < len(party)
             and party[mem[CUR_BATTLE_MON]].species_id == battle.active.species_id
             else None),
            self.mechanics_verified,
            (battle.opponent if self.mechanics_verified and menu_kind == 'switch_prompt'
             and battle.opponent and battle.opponent.hp > 0 else None),
            bool(self.mechanics_verified and mem[GOT_CUT_EVENT_BYTE] & GOT_CUT_EVENT_MASK),
            bool(self.mechanics_verified and
                 mem[ROUTE_102_TREE_CHOPPED_EVENT_BYTE] & ROUTE_102_TREE_CHOPPED_EVENT_MASK),
            bool(self.mechanics_verified and
                 mem[ROUTE_102_RIVAL_EVENT_BYTE] & ROUTE_102_RIVAL_EVENT_MASK),
            map_exits(self.data, mem, width, height) if self.mechanics_verified else (),
            getattr(emulator, "frame_count", 0),
            box_roster=boxes, storage_verified=storage_ok, current_box=current_box,
            party_cursor=_party_cursor(screen_lines, screen_tiles),
            pc_selection=(mem[0xCB2A] + mem[0xCB2B] if self.mechanics_verified and
                          any('CANCEL' in line for line in screen_lines) and
                          mem[0xCB2A] + mem[0xCB2B] <= 20 else None),
            box_names=tuple(_decode_name(
                bytes(mem[0xDB79 + i * 9 + j] for j in range(9))) for i in range(14)) if self.mechanics_verified else (),
            battle_participants=mem[0xC664] & 63 if self.mechanics_verified and kind != 'none' else None,
            escape_allowed=battle_restrictions(mem, kind, self.mechanics_verified)[0],
            switch_allowed=battle_restrictions(mem, kind, self.mechanics_verified)[1],
            overworld_objects=active_objects(mem, width, height) if self.mechanics_verified and kind == 'none' else None,
            # Player object at D4D6: OBJECT_FACING +08; next/current XY +10/+12.
            # Read-only native pose avoids inferring facing from sent inputs.
            player_facing=({0: 'down', 4: 'up', 8: 'left', 12: 'right'}.get(mem[0xD4DE])
                           if self.mechanics_verified and kind == 'none' else None),
            player_moving=(any(mem[0xD4E6 + i] != mem[0xD4E8 + i] for i in range(2))
                           if self.mechanics_verified and kind == 'none' else False),
            player_next_position=(player_destination(mem, width, height)
                                  if self.mechanics_verified and kind == 'none' else None),
            # EVENT_BEAT_WHITNEY = 1221, wEventFlags = DA72 in v6.1c.
            # Route103's two Slowpoke objects use this exact disappearance flag.
            route_103_slowpoke_cleared=(bool(mem[0xDB0A] & 0x20)
                                       if self.mechanics_verified else None),
            # wTMsHMs=D859, NUM_TMS=50; exact-build persistent HM quantities.
            owned_hms=tuple(name for i, name in enumerate(HM_NAMES)
                if self.mechanics_verified and mem[0xD859 + 50 + i]),
            # SetStrengthFlag at ROM CD66: ld hl,DBF9; set 0,[hl].
            strength_active=bool(mem[0xDBF9] & 1) if self.mechanics_verified else None,
            story_milestones=story_milestones(mem, self.mechanics_verified, (group, number)),
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
