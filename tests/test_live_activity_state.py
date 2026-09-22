"""Activity must represent pending work, including completion and cancellation."""
from concurrent.futures import Future
from types import SimpleNamespace as NS

import pytest

from jpp.agent.live_activity import activity


def owner():
    return NS(paused=False, decision_future=None, vision_future=None,
              strategy=NS(future=None, payload=None, label='Qwen'), route=NS(now=11),
              _provider_label=lambda: 'Laya', provider_health='ready',
              held_action=None, pending_options={'yes': 'Board the ferry'})


@pytest.mark.parametrize('kind', ['decision', 'strategy', 'vision'])
def test_pending_work_is_visible_and_completion_clears_thinking(kind):
    controller = owner()
    future = Future()
    target, field = ((controller.strategy, 'future') if kind == 'strategy'
                     else (controller, kind + '_future'))
    setattr(target, field, future)
    status = activity(controller)
    assert status['kind'] == 'thinking'
    assert status['provider'] == ('Laya' if kind == 'decision' else 'Qwen')
    assert status['elapsed_seconds'] >= 0
    if kind == 'decision':
        assert status['options'] == ['Board the ferry']
    future.set_result(None)
    assert activity(controller)['kind'] == 'waiting'
    assert controller._visible_work is None


def test_cancel_pause_and_automatic_controls_are_not_model_thinking():
    controller = owner()
    controller.decision_future = Future()
    controller.decision_future.cancel()
    controller.held_action = 'a'
    assert activity(controller)['kind'] == 'executing'
    controller.paused = True
    controller.pause_reason = 'Paused by user'
    assert activity(controller) == {'kind': 'paused', 'phase': 'Paused by user'}


def test_panel_replaces_stale_battle_with_actual_pending_work(monkeypatch, tmp_path):
    import pygame
    from jpp.character.animation import Animation
    from jpp.live_ui import LiveUI, SIZE
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        rendered = []
        original = ui.text

        def capture(value, *args, **kwargs):
            rendered.append(str(value))
            return original(value, *args, **kwargs)

        ui.text = capture
        progress = {'control_mode': 'ai', 'tactical_provider': 'laya',
                    'agent_state': {'decision': {'action': 'Use Bite'},
                                    'activity': {'kind': 'thinking', 'provider': 'Laya',
                                                 'goal': 'Board the ferry',
                                                 'options': ['Accept passage', 'Decline'],
                                                 'elapsed_seconds': 2.5}}}
        ui._thoughts({'laya': []}, Animation(), progress)
        assert 'Laya thinking…' in rendered
        assert 'Board the ferry' in rendered
        assert any('2.5s' in text for text in rendered)
        assert 'Use Bite' not in rendered
        pygame.image.save(ui.canvas, str(tmp_path / 'thinking-panel.png'))
        rendered.clear()
        progress['agent_state']['activity'] = {'kind': 'waiting', 'phase': 'Observing game response'}
        ui._thoughts({'laya': []}, Animation(), progress)
        assert 'Observing game response' in rendered
        assert not any('thinking' in text for text in rendered)
    finally:
        pygame.quit()


def test_duplicate_option_labels_do_not_hide_distinct_options():
    controller = owner()
    controller.strategy.future = Future()
    controller.strategy.payload = {'candidates': [
        {'id': str(i), 'label': label} for i, label in enumerate(
            ['Talk to sprite', 'Talk to sprite', 'Talk to sprite', 'Leave gym'])]}
    assert activity(controller)['options'] == ['Talk to sprite', 'Leave gym']
