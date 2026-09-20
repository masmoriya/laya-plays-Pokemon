import os
from types import SimpleNamespace

import numpy as np
import pygame

from jpp.character.animation import Animation
from jpp.live_ui import LEFT, LiveUI, SIZE
from jpp.pokemon_sprites import _surface
from jpp.route_progress import RouteProgress
from jpp.route_progress import MAIN
from jpp.terrain_capture import OverworldSprite


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
        ui.draw(frame, progress, _state(), Animation(), {"jev": [], "luna": []}, journey)
        assert "map_toggle" not in ui.actions
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


def test_map_draws_current_sprites_without_stale_npc_ghosts():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        panel = ui.panels.map_panel
        map_key = "14:04"
        ui.map_entities = (OverworldSprite("oam:8", map_key, 32, 40, bytes(1024)),)
        ui.player_marker = OverworldSprite("player", map_key, 64, 56, bytes(16 * 16 * 4))
        journey = SimpleNamespace(
            tiles={}, tile_revision=0, entity_revision=1,
            entities={map_key: {"oam:4": (16, 24, bytes(1024)), "oam:8": (32, 40, bytes(1024))}},
        )
        calls = []
        panel._sprite = lambda *args, **kwargs: calls.append((args[3:6], kwargs))

        panel._area(_state(), journey, pygame.Rect(0, 0, 400, 300))

        assert calls == [((32, 40, bytes(1024)), {}),
                         ((64, 56, bytes(16 * 16 * 4)), {})]
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


def test_map_location_border_follows_captured_sprite():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        panel = ui.panels.map_panel
        state = _state()
        ui.player_marker = OverworldSprite(
            "player", f"{state.map_group:02X}:{state.map_number:02X}",
            120, 68, bytes(1024))

        source = panel._source_rect(state, 80, 60)
        assert source == pygame.Rect(0, 0, 640, 480)
        assert panel._location_rect(state, "14:04", pygame.Rect(50, 0, 300, 300),
                                    pygame.Rect(0, 0, 320, 320), 0.9375).width > 30
        ui.canvas.fill((0, 0, 0))
        panel._area(state, SimpleNamespace(tiles={}, tile_revision=0), pygame.Rect(0, 0, 400, 300))
        assert ui.canvas.get_at((153, 55))[:3] == (236, 157, 111)
    finally:
        pygame.quit()


def test_transparent_sprite_pixels_show_the_terrain_underneath():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        ui.canvas.fill((50, 60, 70))
        pixels = bytearray(1024)
        pixels[4:8] = bytes((200, 100, 50, 255))
        ui.panels.map_panel._sprite(pygame.Rect(0, 0, 16, 16), pygame.Rect(0, 0, 16, 16),
                                   1, 0, 0, bytes(pixels))
        assert ui.canvas.get_at((0, 0))[:3] == (50, 60, 70)
        assert ui.canvas.get_at((1, 0))[:3] == (200, 100, 50)
    finally:
        pygame.quit()


def test_black_sprite_backdrop_is_transparent_but_colored_pixels_remain():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        ui.canvas.fill((50, 60, 70))
        pixels = bytearray((0, 0, 0, 255) * 256)
        for y in range(5, 11):
            for x in range(5, 11):
                offset = (y * 16 + x) * 4
                pixels[offset:offset + 4] = bytes((220, 130, 40, 255))
        ui.panels.map_panel._sprite(pygame.Rect(0, 0, 16, 16), pygame.Rect(0, 0, 16, 16),
                                    1, 0, 0, bytes(pixels))
        assert ui.canvas.get_at((0, 0))[:3] == (50, 60, 70)
        assert ui.canvas.get_at((7, 7))[:3] == (220, 130, 40)
    finally:
        pygame.quit()
