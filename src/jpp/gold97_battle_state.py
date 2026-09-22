"""Reforged party/battle structures from the pinned macros/wram.asm layout."""
from .decode import Mon
from .gold97_catalog import item_name, move_name
from .agent.gold97_mechanics import move_info

BATTLE_MON = 0xC62C
PLAYER_STAGES = 0xC6CC
ENEMY_STAGES = 0xC6D4


def battle_restrictions(mem, kind, verified):
    """Pinned core.asm TryToRunAwayFromBattle and BattleMenuPKMN checks."""
    if not verified or kind == 'none':
        return None, None
    trapped = bool(mem[0xC671] & 0x80 or mem[0xC730])
    battle_type = mem[0xD230]
    # Debug and contest allow fleeing before checking trapping effects.
    escape = (battle_type in {2, 6} or
              (kind == 'wild' and battle_type not in {7, 9, 11, 12} and not trapped))
    return escape, not trapped


_TYPE_NAMES = (
    "NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BIRD", "BUG",
    "DRAGON", "DARK", "STEEL", *("UNKNOWN",) * 10,
    "FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE", "GHOST",
)


def _max_pp(move, raw):
    info = move_info(move)
    if not info:
        return 0
    base = info['pp']
    return min(61, base + (base // 5) * (raw >> 6))


def _status(value):
    if value & 7:
        return "sleep"
    for bit, label in ((3, "poison"), (4, "burn"), (5, "freeze"), (6, "paralysis")):
        if value & (1 << bit):
            return label
    return "none"


def _stages(mem, address):
    values = tuple(mem[address + i] for i in range(7))
    return tuple(value - 7 for value in values) if all(1 <= v <= 13 for v in values) else ()


def _u16(mem, address: int) -> int:
    return (mem[address] << 8) | mem[address + 1]


def _types(*identifiers):
    values = tuple(_TYPE_NAMES[value] if value < len(_TYPE_NAMES) else "UNKNOWN" for value in identifiers)
    return tuple(dict.fromkeys(values))


def decode_mon(data, mem, base, slot, battle=False, species_id=None, verified=False):
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
    return Mon(slot=slot, species=data.name(species), level=level, hp=hp, max_hp=max_hp,
               status=_status(status), types=types, moves=moves, pp=pp,
               held_item=item_name(mem[base + 1]),
               species_id=species, species_data=data.species_data(species),
               experience=(int.from_bytes(bytes(mem[base + i] for i in range(8, 11)), 'big')
                           if verified and not battle else None),
               identity=(''.join(f'{mem[base + i]:02x}' for i in (6, 7, 21, 22, 29, 30))
                         if verified and not battle else None),
               growth_rate=(getattr(data.species_data(species), 'growth_rate', None)
                            if verified else None),
               stats=tuple(_u16(mem, base + (20 if battle else 38) + i * 2)
                           for i in range(5)),
               stages=_stages(mem, PLAYER_STAGES if base == BATTLE_MON else ENEMY_STAGES)
                      if battle and verified else (),
               move_slots=indices,
               max_pp=tuple(_max_pp(move, mem[base + (8 if battle else 23) + i])
                            for move, i in zip(moves, indices)))
