"""Evidence-based notebook and atomic exports; no invented model thoughts."""

import json
import re
from pathlib import Path

from .experience import prerequisites
from ..route_progress import MAIN


def notebook(controller):
    memory = controller.memory
    data = controller.strategy.data
    plan = data.get('plan') or {}
    return {
        'run_id': memory.run_id, 'goal': MAIN.get(controller.route.now, 'Journey complete'),
        'next': plan.get('explanation') or (controller.strategy.target or {}).get('label', 'No committed plan'),
        'blocker': controller.pause_reason or '',
        'completed': sorted(controller.route.completed),
        'manual': sorted(controller.route.manual_history),
        'scope': prerequisites(memory, controller.route.now),
        'learned': [*memory.world.get('facts', []), *data.get('clues', [])],
        'attempts': memory.experience.failures(controller.route.now),
        'events': memory.experience.recent(100),
        'limits': 'Observed state changes are not proof of milestone completion. '
                  'Experience survives restores; current facts follow the checkpoint.',
    }


def text_lines(data, view='Now', query=''):
    if view == 'Now':
        lines = [data['goal'], 'Next: ' + data['next'],
                 'Blocked: ' + data['blocker'] if data['blocker'] else 'No reported blocker',
                 f"{len(set(data['completed']) - set(data.get('manual', [])))} verified milestones · "
                 f"{len(data.get('manual', []))} manual confirmations"]
    elif view == 'Learned':
        lines = [f"{item.get('map', '')} · {item.get('text', item.get('value', ''))} "
                 f"[{item.get('source', item.get('kind', 'observation'))}: {item.get('id', 'recorded fact')}]"
                 for item in reversed(data['learned'])]
    else:
        lines = [f"{item['label']} · {item['reason']} · Retry: {item['retry_when']}"
                 for item in reversed(data['attempts'])]
        lines += [event_line(item) for item in data['events'] if item['kind'] != 'decision']
    return [line.replace('→', 'to') for line in lines
            if query.casefold() in line.casefold()] or ['No matching records']


def event_line(item):
    if item['kind'] == 'action':
        position = (item.get('before') or {}).get('position', '')
        return f"#{item['id']} {item['action']} at {position} · {item.get('source', 'executor')}"
    if item['kind'] == 'outcome':
        return f"After #{item['decision_id']}: {item['outcome']}"
    return f"#{item['id']} {item['kind']} · " + str(item.get('detail') or item.get('reason') or '')


def export_notebook(controller, reason='manual', directory=None):
    memory = controller.memory
    if directory is None:
        # Keep test/alternate databases' exports alongside their own database.
        database = memory.db.execute('PRAGMA database_list').fetchone()[2]
        if not database:
            return None
        directory = Path(database).parent / 'notes'
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^A-Za-z0-9_.-]+', '-', memory.run_id).strip('.-') or 'run'
    data = notebook(controller)
    data['export_reason'] = reason
    return write_export(data, directory, name)


def write_export(data, directory, name):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    content = f"# {data['run_id']}\n\n" + data['limits'] + '\n'
    for view in ('Now', 'Learned', 'Attempts'):
        content += '\n## ' + view + '\n\n' + '\n'.join('- ' + line.replace('\n', ' ') for line in text_lines(data, view)) + '\n'
    for suffix, body in (('json', json.dumps(data, indent=2, ensure_ascii=False)), ('md', content)):
        destination = directory / f'{name}.{suffix}'
        temporary = destination.with_suffix('.' + suffix + '.tmp')
        temporary.write_text(body)
        temporary.replace(destination)
    return directory / f'{name}.md'
