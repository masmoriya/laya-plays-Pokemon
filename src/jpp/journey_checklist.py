"""Detailed journey prerequisites shared by the planner and inspector."""


def journey_steps(hms, prerequisite=None):
    steps = []
    if prerequisite:
        steps.extend({'id': f'route.{index}', 'label': label, 'status': 'unverified',
                      'detail': prerequisite.get('completion', '')}
                     for index, label in enumerate(prerequisite.get('steps', ()), 1))
    for move in sorted(hms.get('moves', ()), key=lambda row: row['stage']):
        for step in move['steps']:
            steps.append({**step, 'stage': move['stage'], 'move': move['name'],
                          'detail': (move['location'] + ': ' + move['acquisition']
                                     if step['id'].endswith('.obtain') else
                                     move['use'] if step['id'].endswith('.ready') else '')})
    return steps


def checklist_lines(strategy):
    steps = strategy.get('journey_steps', ())
    if not steps:
        return ['Journey steps unavailable until the next game observation.']
    lines = []
    for step in steps:
        lines.append(f"{step['status'].capitalize()} · {step['label']}")
        if step.get('detail'):
            lines.append(step['detail'])
    return lines
