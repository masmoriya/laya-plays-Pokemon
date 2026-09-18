"""The overlay renders headlessly, so the layout is checked without a display."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from jpp import overlay  # noqa: E402

RECORD = {
    "t": 0.0,
    "goal": "win_lab_rival",
    "kind": "battle",
    "battle_index": 1,
    "state": {"goal": "Win the rival battle in Oak's lab.", "battle": {"turn": 3}},
    "options": {"use_move_scratch": "...", "use_move_ember": "..."},
    "choice": "use_move_ember",
    "probabilities": {"use_move_ember": 0.71, "use_move_scratch": 0.18, "other": 0.11},
    "nouls": {"faints_this_turn": 0.23},
    "latency_ms": 104.0,
    "input_tokens": 420,
    "active_hp_fraction": 0.42,
}


def test_bars_animate_from_the_previous_values_to_the_new():
    view = overlay.Overlay()
    try:
        view.feed(RECORD)
        assert view.shown["use_move_ember"] == 0.0
        for _ in range(3):
            assert view.draw(None)
        assert 0.0 < view.shown["use_move_ember"] <= 0.71
        for _ in range(40):
            view.draw(None)
        assert abs(view.shown["use_move_ember"] - 0.71) < 0.01
    finally:
        pygame.quit()


def test_it_draws_every_option_and_survives_a_missing_frame():
    view = overlay.Overlay()
    try:
        view.feed(RECORD)
        assert view.draw(None)
        assert set(view.target) == set(RECORD["probabilities"])
        assert view.latencies == [104.0]
    finally:
        pygame.quit()


def test_long_state_is_scrolled_rather_than_clipped():
    big = {f"key_{i}": i for i in range(200)}
    rows = overlay.state_lines(big, 78, 20)
    assert len(rows) == 20 and rows[2].strip() == "..."


def test_json_tinting_separates_keys_strings_and_numbers():
    assert overlay.tint('  "species":') == overlay.KEY
    assert overlay.tint('  "CHARMANDER",') == overlay.STRING
    assert overlay.tint("  0.42,") == overlay.NUMBER
