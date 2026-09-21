"""Read or export a saved run without launching a game or changing its database."""

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from .agent.experience import prerequisites
from .agent.notebook import text_lines, write_export
from .route_progress import RouteProgress, MAIN


def read_saved(database, run_id):
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT payload FROM agent_world WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('No saved agent memory for this run')
        world = json.loads(row[0])
        route = RouteProgress.from_dict(world.get('route'))
        strategy = world.get('journey_strategy', {})
        scope = prerequisites(SimpleNamespace(world=world), route.now)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        events, attempts, metrics = [], [], {}
        if 'agent_journal' in tables:
            rows = db.execute('SELECT id,timestamp,kind,payload FROM agent_journal WHERE run_id=? '
                              'ORDER BY id DESC LIMIT 100', (run_id,))
            events = [{'id': i, 'timestamp': t, 'kind': k, **json.loads(p)} for i, t, k, p in rows]
            metrics = dict(db.execute('SELECT kind,count(*) FROM agent_journal WHERE run_id=? GROUP BY kind', (run_id,)))
        if 'agent_attempts' in tables:
            attempts = [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM agent_attempts WHERE run_id=? AND scope=?', (run_id, scope))]
        if not events:
            events = [{'id': f'legacy:{index}', **event}
                      for index, event in reversed(list(enumerate(strategy.get('events', []))))]
    return {'run_id': run_id, 'goal': MAIN.get(route.now, 'Journey complete'),
            'next': (strategy.get('plan') or {}).get('explanation', 'No saved plan'),
            'blocker': '', 'completed': sorted(route.completed), 'manual': route.manual_history,
            'learned': [*world.get('facts', []), *strategy.get('clues', [])],
            'attempts': attempts, 'events': events, 'metrics': metrics, 'scope': scope,
            'limits': 'Saved snapshot; live status is unknown. Experience survives restores; '
                      'world facts follow the checkpoint. Event counts are not success rates.'}


def run(args):
    try:
        data = read_saved(args.database, args.run_id)
    except (sqlite3.Error, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.output:
        name = re.sub(r'[^A-Za-z0-9_.-]+', '-', args.run_id).strip('.-') or 'run'
        write_export(data, args.output, name)
        print(f'Exported {name}.md and {name}.json')
    elif args.json:
        print(json.dumps(data, indent=2))
    else:
        for view in ('Now', 'Learned', 'Attempts'):
            print(view + '\n' + '\n'.join(text_lines(data, view)) + '\n')


def add_parser(sub):
    parser = sub.add_parser('notes', help='inspect or export saved agent memory')
    parser.add_argument('--database', default='data/jev.sqlite')
    parser.add_argument('--run-id', default='run-001')
    parser.add_argument('--output', help='directory for Markdown and JSON exports')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
