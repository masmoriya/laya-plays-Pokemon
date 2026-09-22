"""Actual movement outcomes remain visible alongside asynchronous vision."""
import os
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.live_state import LiveAgentState
from jpp.live_ui import LiveUI, SIZE


def test_continued_controls_record_observed_outcomes(tmp_path):
    memory = Gold97Memory('moves', tmp_path / 'agent.sqlite')
    try:
        live = LiveAgentState(memory)
        state = SimpleNamespace(map_group=10, map_number=1, x=22, y=6, party=(), screen_lines=())
        live.record_action(state, 'up', 'deterministic execution', 'Qwen')
        live.record_action(state, 'up', 'deterministic execution', 'Qwen')
        assert len(live.moves) == 1
        state.y = 5
        live.observe_action(state)
        live.record_action(state, 'left', 'Laya', 'Laya')
        moves = live.snapshot()['moves']
        assert moves[0]['result'] == 'Waiting for result'
        assert moves[1]['result'] == 'Moved [22, 6] to [22, 5]'
        assert moves[1]['selection_source'] == 'Qwen'
    finally:
        memory.close()


@pytest.mark.parametrize('status', ['analyzing', 'completed', 'error'])
@pytest.mark.parametrize('size', [SIZE, (850, 690)])
def test_recent_moves_render_below_vision_above_controls(status, size):
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(size))
        rendered = []
        original = ui.text
        def text(value, position, *args, **kwargs):
            rendered.append((str(value), position))
            return original(value, position, *args, **kwargs)
        ui.text = text
        ui.agent_panel._decision({'strategy': {
            'enabled': True, 'planner': 'Qwen',
            'last_response': {'explanation': 'A long explanation ' * 60},
            'accepted_target': 'Investigate the observed exit', 'selection_source': 'Laya'},
            'agent_state': {'activity': {'kind': 'thinking', 'provider': 'Qwen', 'goal': 'Reach Birdon'},
                            'moves': [{'action': f'Move {d}', 'source': 'Laya',
                                       'result': f'Position {i},5'}
                                      for i, d in enumerate(('up', 'down', 'left', 'right'))],
                            'vision': {'frame': np.zeros((144, 160, 4), dtype=np.uint8),
                                       'status': status}}})
        moves = [(t, pos) for t, pos in rendered if t.startswith('Move ')]
        assert len(moves) == 4
        vision = ui.actions['agent_open:Vision']
        assert all(pos[1] > vision.bottom for _, pos in moves)
        assert all(pos[1] + 36 < ui.agent_panel.box.bottom - 169 for _, pos in moves)
    finally:
        pygame.quit()


def test_move_history_restores_from_actual_action_journal(tmp_path):
    path = tmp_path / 'agent.sqlite'
    memory = Gold97Memory('moves', path)
    state = SimpleNamespace(map_group=10, map_number=1, x=22, y=6, party=(), screen_lines=())
    memory.experience.action(state, 'up', 'deterministic execution', 17,
                             selection_source='Qwen', plan_id=5)
    state.y = 5
    memory.experience.observe(state)
    memory.close()
    memory = Gold97Memory('moves', path)
    try:
        move = LiveAgentState(memory).snapshot()['moves'][0]
        assert move['action'] == 'Move up' and move['selection_source'] == 'Qwen'
        assert move['result'] == 'Moved [22, 6] to [22, 5]'
    finally:
        memory.close()


def test_scrolling_graphics_do_not_finish_move_before_position_changes(tmp_path):
    memory = Gold97Memory('scroll', tmp_path / 'agent.sqlite')
    try:
        live = LiveAgentState(memory)
        state = SimpleNamespace(map_group=1, map_number=1, x=2, y=3,
                                party=(), screen_lines=('BBBB QQQQ',))
        live.record_action(state, 'up', 'Laya')
        state.screen_lines = ('aYBBBBaYBBB QQQQ',)
        live.observe_action(state, overworld=True)
        assert live.pending_move is not None
        assert live.moves[-1]['result'] == 'Waiting for result'
        state.y = 2
        live.observe_action(state, overworld=True)
        assert live.moves[-1]['result'] == 'Moved [2, 3] to [2, 2]'
        live.record_action(state, 'a', 'Laya')
        state.screen_lines = ('Welcome to the hall.',)
        live.observe_action(state, overworld=False)
        assert live.moves[-1]['result'] == 'Screen changed: Welcome to the hall.'
    finally:
        memory.close()


def test_both_model_usage_rows_visible_even_with_zero_calls():
    from jpp.live_agent_panel import LiveAgentPanel
    rendered = []
    ui = SimpleNamespace(tiny=None, text=lambda value, *args, **kwargs: rendered.append(value))
    panel = LiveAgentPanel(ui, pygame.Rect(0, 0, 320, 800))
    panel._usage({'luna': {'calls': 1, 'total_tokens': 2400}}, 'laya', 0, 'Qwen')
    assert rendered == ['Laya · 0 calls · 0 tokens', 'Qwen · 1 call · 2,400 tokens']


def test_known_conversation_keeps_continuations_without_scrolling_duplicates():
    from jpp.agent.journey_evidence import joined_pages
    assert joined_pages(['The hall has holes that', 'will send you back!',
                         'But some can be walked over to get', 'walked over to get by!']) == (
        'The hall has holes that will send you back! But some can be walked over to get by!')
