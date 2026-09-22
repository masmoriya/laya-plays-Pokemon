"""Footer hit targets and strategy summaries at both supported window scales."""

import os

import pygame

from jpp.character.animation import Animation
from jpp.live_ui import LiveUI, SIZE


def test_strategy_toggle_retry_and_play_have_separate_hit_targets():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        progress = {"tactical_available": True, "tactical_label": "Laya",
                    "tactical_auto": False, "agent_paused": True,
                    "strategy": {"enabled": True}}
        labels = []
        text = ui.text

        def capture(value, *args, **kwargs):
            labels.append(value)
            text(value, *args, **kwargs)

        ui.text = capture
        ui._footer(progress)
        assert "Training off" in labels
        assert "Luna on" in labels
        assert "Guide" in labels and "Context" in labels
        rectangles = list(ui.actions.items())
        for i, (name, rect) in enumerate(rectangles):
            for other, other_rect in rectangles[i + 1:]:
                assert not rect.colliderect(other_rect), (name, other)
        for scale in (1, 0.75):
            ui._dest = pygame.Rect(0, 0, int(SIZE[0] * scale), int(SIZE[1] * scale))
            center = ui.actions["toggle_luna"].center
            assert ui.action_at((center[0] * scale, center[1] * scale)) == "toggle_luna"
        progress["training_enabled"] = True
        progress["strategy"]["enabled"] = False
        ui._footer(progress)
        assert "Luna off" in labels
        assert "Training on" in labels
        labels.clear()
        progress.update(control_mode="paused")
        ui._thoughts({"laya": []}, Animation(), progress)
        assert 'Laya paused' in labels
        from jpp.live_strategy import draw_strategy
        ui.strategy_summary = {'known':'Observed clue','next':'Investigate local leads',
                               'rewards':{'points':25,'recent':[]},'intent':'Training Hoppip'}
        draw_strategy(ui, pygame.Rect(0,0,450,500), 10)
        assert '25 points · Training Hoppip' in labels
    finally:
        pygame.quit()
