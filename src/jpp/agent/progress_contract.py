"""Persistent progress facts shared by strategic planning and tactical execution."""
import json


def progress_stamp(memory):
    data = memory.world.get('journey_strategy', {})
    resolved = sorted((n['id'], n.get('outcome')) for n in data.get('npcs', {}).values()
                      if n.get('outcome') in {'collected', 'harvested', 'defeated', 'moved'})
    return json.dumps([memory.world.get('route', {}).get('completed', []),
                       memory.world.get('field_capabilities', []), resolved], sort_keys=True)


def contract(owner, state):
    from .hm_preparation import preparation
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    from .exploration_cycles import counts
    visits = counts(owner.memory)
    repeated = [cell for cell, count in visits.items() if count >= 2]
    target = owner.strategy.target or {}
    return {'task': target.get('label', ''),
            'success': target.get('completion', 'Verified journey milestone or capability gained'),
            'hm': preparation(state, owner.route.now, owner.memory),
            'avoid': [cell for cell in repeated if cell.startswith(key + ':')][-3:],
            'rule': 'Do not repeat exits or completed conversations without changed prerequisites. '
                    'A screen change or arriving at a viewpoint is not task completion.'}
