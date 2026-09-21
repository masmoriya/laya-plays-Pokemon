"""Saved-memory inspection and benchmark isolation use no live provider calls."""

import hashlib
import json
import os
import sqlite3

import pygame
import pytest

from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.journey_knowledge import knowledge
from jpp.benchmark import copy_agent_memory, ExecutorOnly
from jpp.notebook_cli import read_saved
from jpp.live_notebook import NotebookPanel


def test_saved_notes_are_read_only_and_distinguish_manual_progress(tmp_path):
    path = tmp_path / 'memory.sqlite'
    memory = Gold97Memory('run', path)
    knowledge(memory)
    memory.world['route'] = {'completed': [1, 2], 'manual_history': [2]}
    memory.remember('clue', 'Door is locked', '09:02')
    memory.close()
    before = hashlib.sha256(path.read_bytes()).digest()
    data = read_saved(path, 'run')
    assert data['manual'] == [2] and data['completed'] == [1, 2]
    assert data['learned'][0]['value'] == 'Door is locked'
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_benchmark_copies_only_selected_run_and_checkpoint(tmp_path):
    path = tmp_path / 'memory.sqlite'
    memory = Gold97Memory('run', path)
    memory.checkpoint('start')
    memory.checkpoint('later')
    memory.db.execute('CREATE TABLE unrelated(payload BLOB)')
    memory.db.execute('INSERT INTO unrelated VALUES(?)', (bytes(10000),))
    memory.db.commit()
    with sqlite3.connect(':memory:') as destination:
        copy_agent_memory(memory.db, destination, 'run', 'start')
        assert destination.execute('SELECT path FROM agent_world_checkpoints').fetchall() == [('start',)]
        assert not destination.execute("SELECT name FROM sqlite_master WHERE name='unrelated'").fetchall()
    memory.close()


def test_executor_baseline_refuses_to_invent_a_choice():
    provider = ExecutorOnly()
    assert provider.decide_tactical({}, {'a': 'Advance'})['action'] == 'a'
    with pytest.raises(RuntimeError, match='requiring a model'):
        provider.decide_tactical({}, {'left': 'Exit', 'right': 'Explore'})


def test_notebook_owns_search_keys_and_escape_without_quitting():
    panel = NotebookPanel()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n, unicode='n')
    assert not panel.handle(event)
    panel.open = True
    assert panel.handle(event) and panel.query == 'n'
    assert panel.handle(pygame.event.Event(pygame.KEYUP, key=pygame.K_n))
    assert panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode=''))
    assert not panel.open


def test_notebook_hides_underlying_click_targets():
    from jpp.live_ui import LiveUI, SIZE
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        ui.actions['underneath'] = pygame.Rect(400, 200, 50, 30)
        ui.notebook.open = True
        ui.notebook.data = {'goal': 'Continue', 'next': 'No plan', 'blocker': '', 'completed': []}
        ui.notebook.draw(ui)
        assert 'underneath' not in ui.actions
        assert ui.action_at(ui.actions['notes_export'].center) == 'notes_export'
    finally:
        pygame.quit()
