import os
from types import SimpleNamespace

import numpy as np
import pygame

from jpp.character.animation import Animation
from jpp.live_ui import LiveUI, SIZE
from jpp.route_progress import RouteProgress
from jpp.route_progress import MAIN


def _state(battle=False):
    mon = SimpleNamespace(species="FLAMBEAR", level=8, moves=("TACKLE", "EMBER"), pp=(34, 17))
    return SimpleNamespace(area_name="Oak's Lab", locality="Silent Town", map_group=20,
                           map_number=4, map_width=20, map_height=20, x=6, y=4,
                           in_battle=battle, battle=SimpleNamespace(active=mon, opponent=mon))


def test_dashboard_renders_six_members_battle_and_scales_without_overlapping_actions():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    try:
        screen = pygame.display.set_mode(SIZE)
        ui = LiveUI(screen)
        members = [{"species": "A_LONG_POKEMON_NAME", "level": 100,
                    "hp": 12, "max_hp": 49, "held_item": "Poison-cure Berry"} for _ in range(6)]
        progress = {"party": members, "badge_count": 1, "badge_total": 8,
                    "battles": 2, "wins": 1, "losses": 1, "speed": 1}
        journey = SimpleNamespace(route=RouteProgress(), tiles={})
        frame = np.zeros((144, 160, 4), dtype=np.uint8)
        for size in (SIZE, (1200, 800)):
            screen = pygame.display.set_mode(size)
            ui.screen = screen
            for fighting in (False, True):
                for party in (members[:1], members):
                    ui.draw(frame, {**progress, "party": party}, _state(fighting), Animation(),
                            {"luna": ["Ready"], "jev": ["In battle"]}, journey)
            assert len(ui.actions) >= 8
            assert ui._dest.width <= size[0] and ui._dest.height <= size[1]
            snapshot = ui.actions["snapshot"].center
            scaled = (round(ui._dest.x + snapshot[0] * ui._dest.width / SIZE[0]),
                      round(ui._dest.y + snapshot[1] * ui._dest.height / SIZE[1]))
            assert ui.action_at(scaled) == "snapshot"
        assert ui.panels.map_panel._terrain.get_size() == (40 * 8, 40 * 8)
        ui.map_expanded = True
        ui.draw(frame, progress, _state(), Animation(), {"jev": [], "luna": []}, journey)
        assert "map_expand" in ui.actions and "snapshot" not in ui.actions
        assert ui.actions["map_expand"].width >= 70
    finally:
        pygame.quit()


def test_current_journey_step_wraps_in_bold_without_ellipsis():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        route = RouteProgress(completed=set(range(1, 108)))
        rendered = []
        original = ui.text

        def record(value, pos, font=None, color=None, **kwargs):
            if font is ui.small_bold:
                rendered.append(str(value))
            original(value, pos, font, **kwargs)

        ui.text = record
        ui.panels.stages(SimpleNamespace(route=route))
        assert len(rendered) > 1
        assert " ".join(rendered) == f"108. {MAIN[108]}"
        assert not any("…" in line for line in rendered)
    finally:
        pygame.quit()
