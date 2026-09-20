import argparse
from types import SimpleNamespace

import pygame

from jpp.live import SPEEDS, _adjust_speed, _press_held_buttons, add_parser
from jpp.live_controls import handle_keydown
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


def test_speed_controls_walk_the_supported_steps_and_clamp():
    assert _adjust_speed(1.0, -1) == 0.5
    assert _adjust_speed(0.25, -1) == SPEEDS[0]
    assert _adjust_speed(4.0, 1) == SPEEDS[-1]


def test_speed_key_only_changes_the_frame_pacer_setting(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    emulator = FakeEmulator()  # no PyBoy throttle API should be called
    speed = handle_keydown(SimpleNamespace(key=pygame.K_2), emulator, set(), lambda _: None, 1.0)
    assert speed == 2.0


def test_live_resumes_snapshots_by_default_and_can_start_fresh():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser(sub)

    assert parser.parse_args(["live", "--rom", "game.gbc"]).resume is True
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
