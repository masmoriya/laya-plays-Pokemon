"""Planner facts from the same decoded game state and notebook as the dashboard."""
from ..route_progress import MAIN
from .mine_guidance import mine_context


def world_context(owner, state):
    species = getattr(state, 'pokedex_species', ())
    caught = tuple(getattr(state, 'pokedex_caught_ids', ()))
    seen = tuple(getattr(state, 'pokedex_seen_ids', ()))
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    area = owner.memory.map(key)
    current = owner.route.now
    return {
        'source': 'Decoded cartridge state and recorded observations',
        'location': {'map_id': key, 'name': state.area_name,
                     'position': [state.x, state.y],
                     'dimensions': [state.map_width, state.map_height]},
        'journey': {'current': current, 'goal': MAIN.get(current, 'Journey complete'),
                    'completed': sorted(owner.route.completed),
                    'next': next((text for step, text in MAIN.items()
                                  if current is not None and step > current
                                  and step not in owner.route.completed), None),
                    'guidance': mine_context(state, current)},
        'pokedex': {'caught_count': len(caught), 'seen_count': len(seen),
                    'caught_ids': list(caught),
                    'caught_species': [species[i] for i in caught if 0 <= i < len(species)],
                    'ownership_note': 'Caught records do not prove current party or storage availability'},
        'badges': list(getattr(state, 'badge_ids', ())),
        'owned_hms': list(getattr(state, 'owned_hms', ())),
        'trail': area.get('trail', [])[-8:],
    }
