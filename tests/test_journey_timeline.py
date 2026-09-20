import os
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from jpp.journey_art import JourneyArt
from jpp.journey_timeline import MILESTONES, VISIBLE, player_stage, timeline_start
from jpp.live_ui import LiveUI, SIZE
from jpp.route_progress import MAIN, RouteProgress


def test_timeline_tracks_confirmed_milestones_not_every_route_step():
    assert len(MILESTONES) < len(MAIN)
    assert {"Falkner", "Bugsy", "Whitney", "Morty", "Jasmine", "Pryce", "Okera"} <= {
        item.portrait for item in MILESTONES
    }
    assert {"Lorelei", "Koga", "Agatha", "Giovanni", "Lance", "Blue"} <= {
        item.portrait for item in MILESTONES
    }
    completed = {item.step for item in MILESTONES[:16]}
    assert timeline_start(completed) > 0
    assert timeline_start(completed, 999) == len(MILESTONES) - VISIBLE


def test_player_marker_stays_before_unfinished_falkner():
    assert player_stage({1, 2, 3, 4}) == 4
    assert MILESTONES[0].step < player_stage({1, 2, 3, 4}) < MILESTONES[1].step


def test_player_marker_starts_at_silent_town_for_new_journey():
    assert player_stage(set()) == MILESTONES[0].step


def test_rom_art_fails_closed_on_unrecognized_cartridge():
    art = JourneyArt(bytes(0x130000))
    assert art.badge(0) is None
    assert art.portrait("Falkner") is None


def test_timeline_page_controls_and_footer_do_not_overlap():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        route = RouteProgress(completed={item.step for item in MILESTONES[:16]})
        ui.timeline.draw(SimpleNamespace(route=route), {"badge_count": 4})
        assert "timeline_prev" in ui.actions and "timeline_next" in ui.actions
        ui.timeline.page = len(MILESTONES) - VISIBLE
        ui.actions.clear()
        ui.timeline.draw(SimpleNamespace(route=route), {"badge_count": 4})
        assert "timeline_next" not in ui.actions
        assert ui.actions["timeline_prev"].bottom < 176
        ui._footer({"run_seconds": 10, "stream_seconds": 20, "speed": 2})
        assert ui.actions["snapshot"].top > 1004
    finally:
        pygame.quit()


def test_timeline_header_includes_pokemon_caught_and_seen_counts():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        rendered = []
        original = ui.text

        def record(value, pos, font=None, color=None, **kwargs):
            rendered.append(str(value))
            original(value, pos, font, color, **kwargs)

        ui.text = record
        ui.timeline.draw(SimpleNamespace(route=RouteProgress()), {
            "badge_count": 0,
            "pokedex_caught": 3,
            "pokedex_seen": 14,
        })

        header = next(text for text in rendered if "stages" in text)
        assert "Pokémon 3 caught" in header
        assert "14 seen" in header
    finally:
        pygame.quit()


def test_supplied_cartridge_contains_authentic_badges_and_leader_faces():
    cartridge = Path(__file__).resolve().parents[1] / "Gold 97 Reforged v6.1c.gbc"
    if not cartridge.is_file():
        pytest.skip("User-supplied cartridge is not part of the repository")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        art = JourneyArt(cartridge.read_bytes())
        assert all(art.badge(index) is not None for index in range(8))
        assert all(art.portrait(item.portrait) is not None
                   for item in MILESTONES if item.portrait)
    finally:
        pygame.quit()
