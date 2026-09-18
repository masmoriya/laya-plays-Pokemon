"""`jpp state | probe | play | overlay`."""

import argparse
import json
import sys
from pathlib import Path

from . import goals, options, policy
from .decode import decode

RUNS = Path("runs")


def _goal(name, state, latch=None):
    if name:
        return next(g for g in goals.GOALS if g.name == name)
    stack = goals.GoalStack()
    stack.advance(state, latch or _EmptyLatch())
    return stack.current or goals.GOALS[-1]


class _EmptyLatch:
    result = None
    WIN = 0x00


def _pyboy(rom: str, headless: bool):
    from pyboy import PyBoy

    emu = PyBoy(rom, window="null" if headless else "SDL2")
    if headless:
        emu.set_emulation_speed(
            0
        )  # unthrottled: the decisions/sec number is taken here
    return emu


def cmd_state(args):
    """Build the exact request body a branch would send, from a RAM image."""
    mem = Path(args.ram).read_bytes()
    state = decode(mem)
    goal = _goal(args.goal, state)
    if state.in_battle:
        branch = options.battle_branch(
            state, goal, items=options.bag(mem), turn=args.turn
        )
    else:
        waypoint = (state.x + 2, state.y + 3)
        branch = options.tie_branch(state, goal, waypoint, ["left", "right"])
    print(
        json.dumps(
            {
                "model": policy.MODEL,
                "state": branch.state,
                "questions": policy.questions_for(branch),
            },
            indent=1,
        )
    )


def cmd_probe(args):
    from .loop import probe

    emu = _pyboy(args.rom, headless=False)
    try:
        probe(emu, ticks=args.ticks)
    finally:
        emu.stop(save=False)


def cmd_play(args):
    from .loop import play

    RUNS.mkdir(exist_ok=True)
    log = Path(args.out) if args.out else RUNS / "run.jsonl"
    emu = _pyboy(args.rom, headless=args.headless)
    client = policy.JevClient(replay_dir=args.replay)
    try:
        records = play(
            emu,
            policy.Policy(client, enabled=not args.no_jev),
            max_decisions=args.max_decisions,
            log_path=log,
        )
    finally:
        emu.stop(save=False)
    print(f"{len(records)} decisions -> {log}")


def cmd_overlay(args):
    from .overlay import run_replay

    run_replay(Path(args.replay), rate=args.rate)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jpp")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("state", help="print the Jev request for a RAM image")
    p.add_argument("--ram", required=True)
    p.add_argument("--goal", choices=[g.name for g in goals.GOALS])
    p.add_argument("--turn", type=int, default=None)
    p.set_defaults(func=cmd_state)

    p = sub.add_parser(
        "probe", help="walk the route by hand and watch the decoded state"
    )
    p.add_argument("--rom", required=True)
    p.add_argument("--ticks", type=int, default=100_000)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("play", help="run the agent")
    p.add_argument("--rom", required=True)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--max-decisions", type=int, default=50)
    p.add_argument("--out")
    p.add_argument(
        "--replay", help="answer from recorded fixtures instead of the network"
    )
    p.add_argument(
        "--no-jev", action="store_true", help="code defaults only, for a baseline"
    )
    p.set_defaults(func=cmd_play)

    p = sub.add_parser(
        "overlay", help="the 1280x720 window, live or replaying a run file"
    )
    p.add_argument("--replay", required=True)
    p.add_argument("--rate", type=float, default=2.0, help="decisions per second")
    p.set_defaults(func=cmd_overlay)

    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
