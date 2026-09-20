"""Command-line choices for checkpoint versus cartridge save startup."""

from pathlib import Path

from .live_controls import SPEEDS


def add_parser(sub):
    parser = sub.add_parser("live", help="play locally with keyboard and compact run HUD")
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--run-id", default="run-001")
    parser.add_argument("--rules", default="config/game_rules.json")
    parser.add_argument("--player-name", help="override configured player name")
    parser.add_argument("--starter", help="preferred starter species, overrides rule order")
    parser.add_argument("--game-adapter", choices=["auto", "red", "gold97", "generic"], default="auto")
    parser.add_argument("--provider", choices=["fake", "jev", "laya"],
                        help="tactical provider; defaults to AGENT_PROVIDER or Laya")
    parser.add_argument("--speed", type=float, choices=SPEEDS, default=1.0, help="emulation speed multiplier")
    parser.add_argument("--resume", action="store_true", help="load the latest snapshot (default)")
    parser.add_argument("--new", dest="resume", action="store_false",
                        help="boot from title without loading a snapshot")
    parser.add_argument("--native-save", action="store_true",
                        help="boot to title and choose the cartridge's in-game Continue option")
    parser.set_defaults(resume=True)

    def launch(args):
        from .live import run
        return run(args.rom, args.state, args.run_id, args.rules, args.player_name,
                   args.starter, args.game_adapter, args.speed, args.resume, args.native_save,
                   args.provider)

    parser.set_defaults(func=launch)
