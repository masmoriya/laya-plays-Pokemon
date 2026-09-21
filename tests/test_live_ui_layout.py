import os
from types import SimpleNamespace

import numpy as np
import pygame

from jpp.character.animation import Animation
from jpp.live_ui import LEFT, LiveUI, SIZE
from jpp.live_activity import collapse_repeated
from jpp.gold97_collision import Gold97CollisionMap
from jpp.pokemon_sprites import _surface
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
        terrain = Gold97CollisionMap((20, 4), 20, 20, bytes(400))
        ui.map_state.update(_state(), terrain, ready=True, overworld=True)
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
        assert ui.panels.map_panel.grid.surface is not None
        ui.draw(frame, progress, _state(), Animation(), {"jev": [], "luna": []}, journey)
        assert "map_grid" in ui.actions
        assert "map_artwork" in ui.actions
        assert "map_expand" not in ui.actions
    finally:
        pygame.quit()


def test_dashboard_distinguishes_laya_health_from_autonomous_mode():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        rendered = []
        original = ui.text

        def capture(value, pos, font=None, color=None, **kwargs):
            if pos == (LEFT.x + 75, LEFT.y + 14):
                rendered.append(str(value))
            if color is None:
                original(value, pos, font, **kwargs)
            else:
                original(value, pos, font, color, **kwargs)

        # Keep the assertion focused on the status text without depending on a
        # particular font rasterization.
        ui.text = capture
        ui._thoughts(
            {"luna": [], "laya": []}, Animation(),
            {"tactical_provider": "laya", "tactical_label": "Laya",
             "tactical_status": "unavailable", "model_usage": {"laya": {}, "luna": {}}},
        )
        assert "Unavailable" in rendered
    finally:
        pygame.quit()


def test_activity_uses_available_space_and_scrolls_to_older_events():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        rendered = []
        ui.text = lambda value, pos, font=None, color=None, **kwargs: rendered.append(str(value))
        entries = [f"Event {index}" for index in range(40)]
        progress = {"tactical_provider": "laya", "model_usage": {"laya": {"calls": 2,
                    "input_tokens": 123, "output_tokens": 4}, "luna": {"calls": 1,
                    "input_tokens": 6, "output_tokens": 7}}}
        ui._thoughts({"laya": entries}, Animation(), progress)
        assert "Event 39" in rendered
        assert "Event 0" not in rendered
        assert any("123 in / 4 out" in line for line in rendered)
        assert any("Luna 1 calls · 6 in / 7 out" in line for line in rendered)
        assert "Luna" not in rendered
        ui._dest = pygame.Rect(0, 0, *SIZE)
        ui.scroll_activity(ui.activity_bounds.center, 20)
        rendered.clear()
        ui._thoughts({"laya": entries}, Animation(), progress)
        assert "Event 0" in rendered
    finally:
        pygame.quit()


def test_activity_collapses_repeated_events_and_discloses_exact_model_input():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        rendered = []
        ui.text = lambda value, pos, font=None, color=None, **kwargs: rendered.append(str(value))
        progress = {
            "tactical_provider": "laya",
            "model_usage": {"laya": {}, "luna": {}},
            "model_input": {
                "provider": "Laya",
                "state": {"decision_kind": "overworld", "position": {"x": 3, "y": 5}},
                "questions": {"next_action": {"criteria": {"up": "walk north"}}},
            },
        }

        ui._thoughts({"laya": ["Executor chose a"] * 6}, Animation(), progress)
        assert "Executor chose a ×6" in rendered
        assert "model_input" in ui.actions

        ui.show_model_input = True
        rendered.clear()
        ui._thoughts({"laya": []}, Animation(), progress)
        assert "Laya input" in rendered
        assert any('"decision_kind": "overworld"' in line for line in rendered)
    finally:
        pygame.quit()


def test_activity_repeat_collapsing_only_groups_adjacent_events():
    assert collapse_repeated(["a", "a", "b", "a"]) == ["a ×2", "b", "a"]


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


def test_rom_sprite_white_pixels_are_opaque():
    pygame.init()
    try:
        sprite = _surface(bytes(4 * 4 * 16), 4)
        assert sprite.get_at((0, 0)) == (255, 255, 255, 255)
        assert sprite.get_at((16, 16)) == (255, 255, 255, 255)
    finally:
        pygame.quit()


def test_map_always_shows_full_area_without_a_second_zoom():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        panel = LiveUI(pygame.display.set_mode(SIZE)).panels.map_panel
        state = _state()
        assert panel._source_rect(state, 80, 60) == pygame.Rect(0, 0, 640, 480)
    finally:
        pygame.quit()
