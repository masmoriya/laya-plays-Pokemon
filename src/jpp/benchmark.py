"""Repeat real checkpoint runs in isolated ROM/database copies."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


class ExecutorOnly:
    """Baseline stops at ambiguity instead of impersonating a model."""
    usage_provider = 'executor'

    def decide_tactical(self, state, options):
        if len(options) != 1:
            raise RuntimeError('Executor baseline reached a choice requiring a model')
        return {'action': next(iter(options)), 'request_made': False}


def run(args):
    from pyboy import PyBoy
    from .gold97_adapter import Gold97Adapter
    from .agent.factory import provider_from_env
    from .agent.policy_adapter import ProviderPolicy
    from .agent.gold97_play import play_gold97

    rom, checkpoint = Path(args.rom), Path(args.state)
    if args.repeats < 1 or args.frames < 1 or args.seconds <= 0:
        raise SystemExit('Repeats, frame budget, and time budget must be positive')
    if any((Path(args.output) / f'{mode}-{repeat + 1}.jsonl').exists()
           for mode in args.modes for repeat in range(args.repeats)):
        raise SystemExit('Use a new output directory to keep comparisons separate')
    manifest = {'rom_sha256': hashlib.sha256(rom.read_bytes()).hexdigest(),
                'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                'provider': args.provider, 'frames_budget': args.frames,
                'planner_model': os.environ.get('CODEX_MODEL', 'gpt-5.6-luna'),
                'seconds_budget': args.seconds, 'repeats': args.repeats, 'runs': []}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # Snapshot the database once so every mode/repeat starts with identical knowledge.
    with tempfile.TemporaryDirectory(prefix='jpp-benchmark-') as directory:
        base = Path(directory)
        memory_path = str(checkpoint)
        if args.database:
            with sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True) as source:
                source.execute('BEGIN')
                rows = source.execute('SELECT path FROM agent_world_checkpoints WHERE run_id=?', (args.run_id,))
                memory_path = next((p for p, in rows if Path(p).resolve() == checkpoint.resolve()), None)
                if memory_path is None:
                    raise SystemExit('Checkpoint has no matching agent memory for this run')
                with sqlite3.connect(base / 'baseline.sqlite') as target:
                    copy_agent_memory(source, target, args.run_id, memory_path)
        for mode in args.modes:
            for repeat in range(args.repeats):
                name = f'{mode}-{repeat + 1}'
                scratch = base / name
                scratch.mkdir()
                local_rom = scratch / 'game.gbc'
                shutil.copyfile(rom, local_rom)
                database = scratch / 'run.sqlite'
                if args.database:
                    shutil.copyfile(base / 'baseline.sqlite', database)
                provider = ExecutorOnly() if args.provider == 'executor' else provider_from_env(args.provider)
                emulator = PyBoy(str(local_rom), window='null', sound_emulated=False)
                try:
                    emulator.set_emulation_speed(0)
                    with checkpoint.open('rb') as handle:
                        emulator.load_state(handle)
                    summary = []
                    play_gold97(emulator, Gold97Adapter(local_rom), ProviderPolicy(provider),
                                args.frames, log_path=output / f'{name}.jsonl',
                                run_id=args.run_id, database=database,
                                checkpoint_dir=scratch / 'checkpoints', memory_state=memory_path,
                                max_frames=args.frames, max_seconds=args.seconds,
                                strategy_enabled=mode == 'on', on_summary=summary.append)
                    result = {'mode': mode, 'repeat': repeat + 1, **summary[0]}
                    manifest['runs'].append(result)
                    print(f"{name}: {result['actions']} actions, {result['frames']} frames; {result['blocker'] or 'budget ended'}")
                finally:
                    emulator.stop(save=False)
                (output / 'comparison.json').write_text(json.dumps(manifest, indent=2))
    return 0


def copy_agent_memory(source, target, run_id, checkpoint):
    """Exclude terrain/artwork history: benchmarks need only agent-owned state."""
    for table in ('agent_world', 'agent_world_checkpoints', 'agent_rewards',
                  'agent_playback', 'agent_attempts'):
        schema = source.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',
                                ('table', table)).fetchone()
        if schema is None:
            continue
        target.execute(schema[0])
        query = f'SELECT * FROM {table} WHERE run_id=?'
        parameters = [run_id]
        if table == 'agent_world_checkpoints':
            query += ' AND path=?'
            parameters.append(checkpoint)
        for row in source.execute(query, parameters):
            placeholders = ','.join('?' for _ in row)
            target.execute(f'INSERT INTO {table} VALUES({placeholders})', row)
    target.commit()


def add_parser(sub):
    parser = sub.add_parser('benchmark', help='compare real checkpoint runs without changing player saves')
    parser.add_argument('--rom', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--database', help='optional database containing this checkpoint memory')
    parser.add_argument('--run-id', default='run-001')
    parser.add_argument('--provider', choices=('executor', 'laya', 'jev'), default='executor')
    parser.add_argument('--modes', nargs='+', choices=('off', 'on'), default=['off'])
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--frames', type=int, default=18000)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--output', required=True)
    parser.set_defaults(func=run)
