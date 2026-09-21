"""Offline mechanics pinned to Reforged source and verified cartridge tables."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

REFERENCE = json.loads(Path(__file__).with_suffix('.json').read_text())
PHYSICAL_TYPES = frozenset(REFERENCE['physical_types'])
TYPE_CHART = REFERENCE['type_chart']
MOVES = {row['name']: row for row in REFERENCE['moves']}
MOVES['PSYCHIC'] = MOVES['PSYCHIC M']


def move_info(name):
    return MOVES.get(str(name).upper().replace('-', ' ').replace('_', ' '))


@lru_cache(maxsize=4)
def compatible(rom):
    """Check the exact move and type tables, not just the cartridge title."""
    start = REFERENCE['move_table_offset']
    moves = rom[start:start + 7 * len(REFERENCE['moves'])]
    start = REFERENCE['type_chart_offset']
    chart = bytes.fromhex(REFERENCE['type_chart_hex'])
    return (hashlib.sha256(rom).hexdigest() == REFERENCE['rom_sha256']
            and hashlib.sha256(moves).hexdigest() == REFERENCE['move_table_sha256']
            and rom[start:start + len(chart)] == chart)


def multiplier(kind, defenders):
    result = 1.0
    for defender in set(defenders):
        result *= TYPE_CHART.get(kind, {}).get(defender, 1.0)
    return result


def types(mon):
    values = tuple(getattr(mon, 'types', ()) or ())
    if values and 'UNKNOWN' not in values:
        return values
    return tuple(getattr(getattr(mon, 'species_data', None), 'types', ()) or ())
