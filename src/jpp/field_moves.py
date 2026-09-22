"""Exact-build HM facts and live capability checks, shared by UI and planners.

Sources: gold97 976507f9e6e605050384e9ec12e9651988ae7c46 maps below,
engine/events/overworld.asm, constants/item_constants.asm, wram.asm.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldMove:
    name: str
    number: int
    stage: int
    badge: int | None
    badge_name: str
    leader: str
    source_map: tuple[int, int]
    source_cell: tuple[int, int] | None
    location: str
    acquisition: str
    source_file: str
    use: str


HMS = (
    FieldMove('Cut', 1, 6, 1, 'Zephyr Badge', 'Falkner', (9, 14), (5, 4),
              "Bill's Family's House", 'Talk to Bill in Pagota City.',
              'BillsFamilysHouse.asm', 'Cut a small tree; progress through Route 102.'),
    FieldMove('Fly', 2, 31, 5, 'Mineral Badge', 'Jasmine', (1, 7), (6, 3),
              'Alloy Cafe', 'Talk to the sailor at (6, 3) in Alloy Cafe.',
              'AlloyCafe.asm', 'Use outdoors to return to a visited destination; walking is an alternative.'),
    FieldMove('Surf', 3, 20, 4, 'Fog Badge', 'Morty', (3, 17), None,
              'Slowpoke Well B2F', 'Finish the Rocket event; the elder gives HM03.',
              'SlowpokeWellB2F.asm', 'Face accessible water and use Surf.'),
    FieldMove('Strength', 4, 12, 2, 'Hive Badge', 'Bugsy', (3, 44), (24, 9),
              'Boulder Mines B4F', 'Collect the item at (24, 9) on B4F.',
              'BoulderMinesB4F.asm', 'Activate Strength, then push a boulder or cart; the 1F rescue has a dry bypass.'),
    FieldMove('Rock Smash', 5, 58, None, '', '', (10, 23), None,
              'Radio Tower 6F', 'Rescue the Director after Giovanni; he gives HM05.',
              'RadioTower6F.asm', 'Face a breakable rock; no badge is required.'),
    FieldMove('Whirlpool', 6, 40, 6, 'Glacier Badge', 'Pryce', (6, 6), (1, 2),
              "Pryce's Family House", 'Meet Pryce in Deepwater Passage, visit him in Frostpoint, '
              'defeat him, then speak to his wife in Frostpoint.',
              'PrycesFamilyHouse.asm', 'Use while surfing at a whirlpool; prepare before Whirl Island.'),
    FieldMove('Waterfall', 7, 35, 8, 'Rising Badge', 'Red', (3, 29), (0, 71),
              'Deepwater Passage B2F', 'Collect the item at (0, 71); Route 115 also awards it later.',
              'DeepwaterPassageB2F.asm', 'Use while surfing, facing a waterfall; requires the eighth badge.'),
)
BY_NAME = {move.name.upper(): move for move in HMS}
HM_NAMES = tuple(move.name for move in HMS)


def normalize(move):
    return move.upper().replace('_', ' ').replace('-', ' ')


def field_ready(state, move):
    """Learning a move is sufficient; ownership is not needed for a learned HM."""
    spec = BY_NAME.get(normalize(move))
    if not getattr(state, 'mechanics_verified', False):
        return False
    if spec is None:
        return normalize(move) == 'FLASH'  # Flash has no badge check in this build.
    return spec.badge is None or f'johto_{spec.badge}' in getattr(state, 'badge_ids', ())


def capabilities(state, milestone):
    verified = bool(getattr(state, 'mechanics_verified', False))
    rows = []
    for move in HMS:
        learned, compatible = [], []
        for slot, mon in enumerate(getattr(state, 'party', ())):
            if move.name.upper() in {normalize(m) for m in getattr(mon, 'moves', ())}:
                learned.append(slot)
            data = getattr(mon, 'species_data', None)
            if move.name in getattr(data, 'field_moves', ()):
                compatible.append(slot)
        owned = move.name in getattr(state, 'owned_hms', ()) if verified else None
        unlocked = field_ready(state, move.name) if verified else None
        ready = bool(verified and learned and unlocked)
        due = milestone is None or milestone >= move.stage
        missing = ('Cartridge state unavailable' if not verified else
                   'Ready to use' if ready else
                   f'Earn the {move.badge_name} from {move.leader}' if learned and not unlocked else
                   f'Obtain HM{move.number:02d} {move.name}' if not owned else
                   f'Bring a Pokemon that can learn {move.name}' if not compatible else
                   f'Teach {move.name} to a compatible party Pokemon')
        tasks = [
            ('obtain', f'Obtain HM{move.number:02d} {move.name}', owned),
            ('party', f'Bring a Pokemon compatible with {move.name}', bool(compatible or learned) if verified else None),
            ('teach', f'Teach {move.name}', bool(learned) if verified else None),
            ('badge', f'Earn the {move.badge_name}' if move.badge else 'No badge required', unlocked),
            ('ready', f'{move.name} ready for field use',
             None if not verified else 'ready' if ready else False),
        ]
        rows.append({'id': f'hm{move.number:02d}', 'name': move.name, 'stage': move.stage,
                     'owned': owned, 'learned_slots': learned if verified else [],
                     'compatible_slots': compatible if verified else [], 'badge_ready': unlocked,
                     'ready': ready, 'due': due, 'next': missing,
                     'active': getattr(state, 'strength_active', None) if move.name == 'Strength' else None,
                     'source_map': list(move.source_map), 'source_cell': move.source_cell,
                     'location': move.location, 'acquisition': move.acquisition, 'use': move.use,
                     'source_file': move.source_file,
                     'steps': [{'id': f'hm{move.number:02d}.{key}', 'label': label,
                                'status': 'unknown' if done is None else 'ready' if done == 'ready'
                                else 'done' if done else 'pending' if due else 'later'}
                               for key, label, done in tasks]})
    return rows
