import argparse
from types import SimpleNamespace

import pygame

from jpp.live import SPEEDS, _adjust_speed, _frames_per_render, _press_held_buttons, add_parser
from jpp.live_controls import (KEYS, handle_keydown, player_control_mode,
                               takes_human_control)
from jpp.live_notebook import NotebookPanel
from jpp.live_ui import format_duration, starter_name
from jpp.progress import ProgressTracker


class FakeEmulator:
    def __init__(self):
        self.presses = []

    def button(self, name, delay):
        self.presses.append((name, delay))


def test_held_buttons_are_renewed_for_one_tick():
    emulator = FakeEmulator()

    _press_held_buttons(emulator, {"left", "up"})

    assert sorted(emulator.presses) == [("left", 1), ("up", 1)]


def test_no_held_buttons_do_not_send_input():
    emulator = FakeEmulator()

    _press_held_buttons(emulator, ())

    assert emulator.presses == []


def test_fast_forward_advances_multiple_game_frames_per_render():
    assert [_frames_per_render(speed) for speed in SPEEDS] == [1, 2, 4, 8]


def test_held_buttons_cover_all_fast_forward_frames():
    emulator = FakeEmulator()

    _press_held_buttons(emulator, {"right"}, frames=8)

    assert emulator.presses == [("right", 8)]


def test_a_is_a_bounded_tap(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    emulator = FakeEmulator()
    held = set()

    handle_keydown(SimpleNamespace(key=pygame.K_z), emulator, held,
                   lambda _: None, 1.0)
    assert held == set()
    assert emulator.presses == [("a", 4)]


def test_speed_controls_walk_the_supported_steps_and_clamp():
    assert SPEEDS == (1.0, 2.0, 4.0, 8.0)
    assert _adjust_speed(1.0, -1) == SPEEDS[0]
    assert _adjust_speed(8.0, 1) == SPEEDS[-1]


def test_speed_key_only_changes_the_frame_pacer_setting(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    emulator = FakeEmulator()  # no PyBoy throttle API should be called
    speed = handle_keydown(SimpleNamespace(key=pygame.K_2), emulator, set(), lambda _: None, 1.0)
    assert speed == 2.0


def test_speed_keys_select_four_and_eight_x(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    emulator = FakeEmulator()
    for key, expected in ((pygame.K_4, 4.0), (pygame.K_8, 8.0)):
        speed = handle_keydown(SimpleNamespace(key=key), emulator, set(), lambda _: None, 1.0)
        assert speed == expected


def test_ctrl_l_toggles_laya_playback(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_CTRL)
    emulator = FakeEmulator()
    actions = []

    speed = handle_keydown(SimpleNamespace(key=pygame.K_l), emulator, set(),
                           actions.append, 1.0)

    assert speed == 1.0
    assert actions == ["toggle_jev"]
    assert emulator.presses == []


def test_ctrl_l_remains_global_while_agent_inspector_is_open():
    panel = NotebookPanel()
    panel.open = True
    panel.view = "Guide"

    consumed = panel.handle(SimpleNamespace(
        type=pygame.KEYDOWN, key=pygame.K_l, mod=pygame.KMOD_CTRL, unicode="l"
    ))

    assert consumed is False
    assert panel.composer == ""


def test_f2_toggles_laya_playback(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    actions = []

    handle_keydown(SimpleNamespace(key=pygame.K_F2), FakeEmulator(), set(),
                   actions.append, 1.0)

    assert actions == ["toggle_jev"]


def test_every_game_control_takes_ownership_from_ai():
    assert {KEYS[key] for key in KEYS if takes_human_control(key, True)} == {
        "up", "down", "left", "right", "a", "b", "start", "select"
    }
    assert not any(takes_human_control(key, False) for key in KEYS)


def test_player_control_mode_keeps_human_ownership_distinct_from_ai_pause():
    assert player_control_mode(True) == "ai"
    assert player_control_mode(False, paused=True) == "human"
    assert player_control_mode(True, paused=True) == "paused"
    assert player_control_mode(True, inspector_open=True) == "paused"


def test_live_resumes_snapshots_by_default_and_can_start_fresh():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser(sub)

    defaults = parser.parse_args(["live", "--rom", "game.gbc"])
    assert defaults.resume is True
    assert defaults.run_id == "laya-tested"
    assert parser.parse_args(["live", "--rom", "game.gbc", "--new"]).resume is False
    assert parser.parse_args(["live", "--rom", "game.gbc", "--native-save"]).native_save


def test_live_hud_uses_elapsed_clock_and_waits_for_an_actual_starter():
    assert format_duration(65) == "01:05"
    assert starter_name({"party": []}) is None
    assert starter_name({"party": [{"species": "MON_00"}]}) is None
    assert starter_name({"party": [{"species": "CHARMANDER"}]}) == "CHARMANDER"


def test_run_clock_keeps_active_time_across_sessions_without_extending_session_clock():
    tracker = ProgressTracker(active_play_seconds=120)
    assert tracker.progress.run_seconds >= 120
    assert tracker.progress.stream_seconds < 1
    tracker.progress.seal_active_time()
    assert tracker.progress.active_play_seconds >= 120


def test_progress_remembers_recent_map_history():
    tracker = ProgressTracker(map_history=["REDS_HOUSE_2F"])
    state = SimpleNamespace(map_name="PALLET_TOWN", party=(), badge_ids=())
    tracker.update(state)
    tracker.update(SimpleNamespace(map_name="ROUTE_1", party=(), badge_ids=()))
    tracker.update(SimpleNamespace(map_name="ROUTE_1", party=(), badge_ids=()))
    assert tracker.progress.map_history == ["REDS_HOUSE_2F", "PALLET_TOWN", "ROUTE_1"]
