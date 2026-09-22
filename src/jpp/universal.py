"""Portable launcher entry point; every cartridge runs from a managed working copy."""

import argparse
import fcntl
import os
import time
from pathlib import Path

from laya_runtime.config import atomic_json
from laya_runtime.server import ensure
from laya_runtime.session import create_session, read_session, session_directory


def run(session):
    directory = session_directory(session["id"])
    work = Path(session["work"])
    with (work / "lineage.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ensure()
        import pygame
        dylibs = Path(pygame.__file__).resolve().parent / ".dylibs"
        if dylibs.is_dir():
            os.environ.setdefault("PYSDL2_DLL_PATH", str(dylibs))
        from pyboy import PyBoy
        emulator = PyBoy(session["rom"], window="null", sound_emulated=False)
        emulator.set_emulation_speed(0)
        try:
            from .game_adapter import adapter_for_rom
            from .gold97_adapter import Gold97Adapter
            adapter = adapter_for_rom(session["rom"], emulator.cartridge_title)
            if session["mode"] == "auto" and isinstance(adapter, Gold97Adapter):
                emulator.stop(save=False)
                emulator = None
                from .managed_live import run_gold97
                run_gold97(session, directory)
                return
            from .visual_loop import VisualLoop
            loop = VisualLoop(emulator, session, directory,
                              adapter=adapter if session["mode"] == "auto" else None)
            screen = None
            if not session["headless"]:
                pygame.init()
                screen = pygame.display.set_mode((640, 576))
                pygame.display.set_caption(f"Laya · {session['title']} · Space: play/pause")
            keys = {pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left",
                    pygame.K_RIGHT: "right", pygame.K_z: "a", pygame.K_x: "b",
                    pygame.K_RETURN: "start", pygame.K_BACKSPACE: "select"}
            try:
                while not loop.stopping:
                    if screen:
                        for event in pygame.event.get():
                            if event.type == pygame.QUIT:
                                loop.command("stop")
                            elif event.type == pygame.KEYDOWN:
                                if event.key == pygame.K_ESCAPE:
                                    loop.command("stop")
                                elif event.key == pygame.K_SPACE:
                                    loop.command("pause" if loop.playing else "play")
                                elif event.key in keys:
                                    loop.command(keys[event.key])
                        surface = pygame.surfarray.make_surface(emulator.screen.ndarray[:, :, :3].swapaxes(0, 1))
                        screen.blit(pygame.transform.scale(surface, (640, 576)), (0, 0))
                        pygame.display.flip()
                    loop.tick()
                    time.sleep(.02)
            finally:
                loop.close()
        finally:
            # The emulator can write only its managed .ram/.rtc files.
            if emulator is not None:
                emulator.stop(save=True)
            pygame.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local visual GB/GBC agent")
    parser.add_argument("--session")
    parser.add_argument("--rom", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--goal", default="")
    parser.add_argument("--mode", choices=["auto", "visual"], default="auto")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)
    if not args.session and not args.rom:
        parser.error("Provide --rom or --session")
    session = read_session(args.session) if args.session else create_session(
        args.rom, state=args.state, goal=args.goal, mode=args.mode, headless=args.headless)
    try:
        run(session)
    except Exception as exc:
        atomic_json(session_directory(session["id"]) / "status.json",
                    {"status": "error", "detail": str(exc)[:400]})
        raise


if __name__ == "__main__":
    main()
