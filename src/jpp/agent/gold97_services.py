"""Small, cartridge-verified service routes for Gold 97.

The controller should never invent a Pokémon Center or Mart location from a
screen guess.  These entrances come from the ROM's map event tables and are
only used after the adapter has identified the active map.
"""

POKE_BALL = 5
POKE_BALL_PRICE = 200
MIN_POKE_BALLS = 5
HEAL_AT_HP_FRACTION = 0.5

# (town map) -> (town tile that warps into the local Pokémon Center)
CENTER_ENTRANCES = {
    (1, 12): ((7, 8), (1, 1)),
    (2, 3): ((3, 12), (2, 2)),
    (4, 5): ((31, 10), (4, 1)),
    (5, 6): ((13, 18), (5, 4)),
    (6, 3): ((13, 12), (6, 1)),
    (7, 5): ((5, 4), (7, 2)),
    (8, 5): ((15, 4), (8, 1)),
    (9, 2): ((27, 28), (9, 7)),
    (10, 1): ((25, 14), (10, 14)),
    (11, 1): ((17, 4), (11, 3)),
    (12, 1): ((9, 10), (12, 2)),
    (13, 1): ((25, 18), (13, 4)),
    (16, 1): ((33, 20), (16, 5)),
    (19, 1): ((33, 16), (19, 2)),
    (20, 3): ((13, 12), (20, 9)),
    (21, 1): ((11, 4), (21, 4)),
    (22, 3): ((5, 22), (22, 2)),
    (24, 4): ((15, 22), (24, 5)),
}

# The Brass Tower stair and door warps lead back to Pagota City, whose Center
# entrance is listed above. These are reverse routes from the ROM's map events.
CENTER_RETREAT_EXITS = {
    (3, 1): ((5, 11), "down"),
    (3, 2): ((0, 1), "left"),
    (3, 3): ((11, 4), "right"),
    (3, 4): ((10, 1), "up"),
    (3, 5): ((5, 5), "down"),
}

# (town map) -> town tile that enters the local Mart.  Marts are visited only
# for balls; healing always wins when both services are needed.
MART_ENTRANCES = {
    (1, 12): ((7, 14), (1, 8)),
    (2, 3): ((15, 4), (2, 12)),
    (4, 5): ((31, 16), (4, 3)),
    (5, 6): ((25, 6), (5, 3)),
    (6, 3): ((15, 8), (6, 5)),
    (8, 5): ((3, 4), (8, 3)),
    (9, 2): ((3, 26), (9, 3)),
    (11, 1): ((23, 10), (11, 4)),
    (12, 1): ((5, 10), (12, 3)),
    (13, 1): ((7, 6), (13, 6)),
    (16, 1): ((35, 26), (16, 2)),
    (19, 1): ((19, 24), (19, 11)),
    (21, 1): ((31, 26), (21, 3)),
    (22, 3): ((11, 22), (22, 1)),
    (24, 4): ((3, 18), (24, 6)),
}


def _raw_map_name(state):
    """Return the catalog identifier when the adapter exposed one."""
    area = getattr(state, "area_name", "") or ""
    return area.casefold().replace("é", "e").replace(" ", "_")


def is_center(state):
    raw = _raw_map_name(state)
    return "pokemon_center" in raw or "pokecenter" in raw


def is_mart(state):
    return "mart" in _raw_map_name(state)


def center_target(state):
    return CENTER_ENTRANCES.get((getattr(state, "map_group", None),
                                 getattr(state, "map_number", None)))


def center_retreat_target(state):
    return CENTER_RETREAT_EXITS.get((getattr(state, "map_group", None),
                                     getattr(state, "map_number", None)))


def mart_target(state):
    return MART_ENTRANCES.get((getattr(state, "map_group", None),
                               getattr(state, "map_number", None)))


def nurse_target(state):
    # The counter at y=2 is not walkable. Talk to the nurse at (5, 1) from
    # (5, 3), as confirmed by a cartridge replay in Pagota's Center.
    return (5, 3)


def needs_healing(state, threshold=HEAL_AT_HP_FRACTION):
    party = tuple(getattr(state, "party", ()) or ())
    if not party:
        return False
    return any(getattr(mon, "status", "none") != "none" or
               _exhausted_attacks(mon) or
               getattr(mon, "hp", 0) <= 0 or
               (getattr(mon, "max_hp", 0) and
                getattr(mon, "hp", 0) / mon.max_hp <= threshold)
               for mon in party)


def novel_capture(state, foe):
    """Only permit a catch for a new, hack-exclusive species."""
    if foe is None or getattr(foe, "species_id", None) is None:
        return False
    from .old_species import hack_exclusive

    species_id = foe.species_id
    caught = set(getattr(state, "pokedex_caught_ids", ()) or ())
    party = {getattr(mon, "species_id", None) for mon in getattr(state, "party", ())}
    return (species_id not in caught and species_id not in party and
            hack_exclusive(getattr(foe, "species", "")))


def should_buy_balls(state):
    balls = getattr(state, "poke_ball_count", None)
    money = getattr(state, "money", None)
    return (balls is not None and money is not None and
            balls < MIN_POKE_BALLS and money >= POKE_BALL_PRICE and
            bool(getattr(state, "party", ())))


def _exhausted_attacks(mon):
    from .gold97_mechanics import move_info
    indices = [i for i, name in enumerate(getattr(mon, 'moves', ()))
               if (info := move_info(name)) and (info['power'] > 0 or info['effect'] == 'OHKO')]
    pp = getattr(mon, 'pp', ())
    return bool(indices) and not any(i < len(pp) and pp[i] > 0 for i in indices)


def fully_recovered(state):
    for mon in getattr(state, 'party', ()):
        if mon.hp != mon.max_hp or getattr(mon, 'status', 'none') != 'none':
            return False
        pp, maximum = getattr(mon, 'pp', ()), getattr(mon, 'max_pp', ())
        if maximum and (len(pp) != len(maximum) or any(a < b for a, b in zip(pp, maximum))):
            return False
        if getattr(mon, 'moves', ()) and not all(value > 0 for value in pp):
            return False
    return True
