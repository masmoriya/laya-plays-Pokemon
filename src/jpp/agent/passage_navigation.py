"""Distinguish returning through an entry from crossing a multi-exit passage."""


def arrival_cell(memory, map_key, destination, milestone):
    entry = memory.world.get('navigation_arrival', {}) if memory else {}
    if (entry.get('map') == map_key and entry.get('from') == destination
            and entry.get('goal') == milestone):
        return entry.get('cell')
    return None


def at_entry(cell, entry):
    return bool(entry is not None and cell is not None
                and abs(cell[0] - entry[0]) + abs(cell[1] - entry[1]) <= 1)


def mark_entry_returns(targets, memory, state, milestone, *, required_next_map=None):
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    for target in targets:
        # Sometimes recovering from an accidental turn-back means walking
        # through the same doorway just used. If the itinerary names that
        # map as the next required hop, it remains the forward route.
        if target.get('destination_key') == required_next_map:
            continue
        entry = arrival_cell(memory, key, target.get('destination_key'), milestone)
        if target['kind'] == 'exit' and not target.get('retreat_reason') and at_entry(target['cell'], entry):
            target['recent_return'] = True
    return targets
