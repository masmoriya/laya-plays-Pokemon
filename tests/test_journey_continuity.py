"""Journey movement and durable interaction regressions."""
from concurrent.futures import Future
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_dialogue import DialogueProgress
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.journey_knowledge import JourneyKnowledge, knowledge
from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


def state():
    return NS(map_group=9, map_number=2, x=24, y=19,
              map_width=40, map_height=36, area_name='Pagota City',
              in_battle=False, badge_ids=(1,), party=(), screen_lines=(),
              mechanics_verified=True, screen_cursor=None,
              battle=NS(kind='none', opponent=None),
              map_exits=((0, 19, 'left', 9, 1),))


@pytest.fixture
def owner(tmp_path):
    c = Gold97Controller('continuity', database=tmp_path / 'memory.sqlite',
                         vision_enabled=False)
    c.route = RouteProgress(set(range(1, 7)))
    c.memory.world['route'] = c.route.to_dict()
    yield c
    c.close()


def test_journey_progress_moves_without_waiting_for_luna(owner):
    s = state()
    s.map_exits += ((24, 35, 'down', 20, 10),)
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    owner.strategy.toggle()
    owner.strategy.observe(s, (), True)
    options = owner.strategy.options(s, terrain)
    assert list(options) == ['left']
    assert owner.strategy.future is None
    assert owner.strategy.target['cell'] == [0, 19]
    assert owner.strategy.target['destination'] == 'Route 102'


def test_new_sprite_does_not_cancel_committed_movement(owner):
    s = state()
    strategy = owner.strategy
    strategy.observe(s, (), True)
    strategy.target = {'id': 'guide:route-102', 'kind': 'exit', 'cell': [0, 19]}
    owner.last = ('09:02', (24, 19), 'left')
    owner.held_action = 'left'
    owner.cooldown = 12
    generation = strategy.generation
    sprite = NS(key='object:4', pixel_x=25*16, pixel_y=18*16)
    strategy.observe(s, (sprite,), True)
    assert strategy.generation == generation
    assert owner.held_action == 'left' and owner.cooldown == 12


def test_restored_apricorn_dialogue_is_saved_before_revisiting(owner, tmp_path):
    s = state()
    observations = owner.strategy.observations
    s.screen_lines = ('',) * 14 + ('WHT APRICORN in', '', 'the ITEM POCKET!', '')
    for _ in range(14):
        observations.observe(s, (), overworld=False, milestone=7, prompt_visible=True)
    clue = observations.data['clues'][0]
    assert clue['text'] == 'WHT APRICORN in the ITEM POCKET!'
    assert clue['map'] == '09:02' and clue['cell'] == [24, 19]
    observations.observe(s, (), overworld=True, milestone=7, prompt_visible=False)
    identifier = clue['interaction']
    assert observations.data['npcs'][identifier]['status'] == 'talked'
    reopened = Gold97Memory('continuity', tmp_path / 'memory.sqlite')
    try:
        assert knowledge(reopened)['clues'][0] == clue
        assert knowledge(reopened)['npcs'][identifier]['status'] == 'talked'
    finally:
        reopened.close()


def test_stale_tilemap_without_visible_box_is_not_a_discovery(owner):
    s = state()
    s.screen_lines = ('',) * 14 + ('WHT APRICORN in', '', 'the ITEM POCKET!', '')
    for _ in range(20):
        owner.strategy.observations.observe(s, (), overworld=False, milestone=7,
                                            prompt_visible=False)
    assert owner.strategy.data['clues'] == []


def test_short_final_page_persists_when_dialogue_closes(owner):
    s = state()
    obs = owner.strategy.observations
    sprite = NS(key='object:4', pixel_x=24*16, pixel_y=18*16)
    obs.observe(s, (sprite,), overworld=True, milestone=7)
    obs.interacted('09:02/object:4')
    s.screen_lines = ('',) * 14 + ('WHT APRICORN!', '', '', '')
    for _ in range(4):
        obs.observe(s, (), overworld=False, milestone=7, prompt_visible=True)
    s.screen_lines = ()
    obs.observe(s, (), overworld=True, milestone=7, prompt_visible=False)
    assert obs.data['npcs']['09:02/object:4']['pages'] == ['WHT APRICORN!']
    assert obs.pending is None


def test_slow_plan_releases_control_and_late_answer_cannot_take_over(owner, monkeypatch):
    strategy = owner.strategy
    s = state()
    s.mechanics_verified = False
    s.map_exits = ()
    strategy.toggle()
    strategy.observe(s, (), True)
    future = Future()
    future.set_running_or_notify_cancel()
    strategy.future = future
    strategy.plan_started_at = 10
    monkeypatch.setattr('jpp.agent.journey_strategy.monotonic', lambda: 71)
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    assert strategy.options(s, terrain)
    assert strategy.future is None and strategy.target is None
    monkeypatch.setattr('jpp.agent.journey_strategy.monotonic', lambda: 100)
    assert not strategy.use_luna  # Do not fill the executor with timed-out plans.
    future.set_result(({'target': 'stale'}, {}))
    strategy.poll_retired()
    assert strategy.target is None and not strategy.retired


def test_route_102_does_not_send_cut_journey_back_to_pagota(owner):
    s = state()
    s.map_number = 1
    s.map_exits = ()
    data = owner.strategy.data
    data['connections'] = [{'from': '09:02', 'to': '09:01', 'at': [0, 19],
                            'arrival': [24, 19], 'direction': 'left'}]
    terrain = Gold97CollisionMap((9, 1), 40, 36, bytes(1440))
    assert all(not c['id'].startswith('guide:return')
               for c in candidates(s, owner.memory, terrain))


def test_unchanged_dialogue_cannot_confirm_forever():
    progress = DialogueProgress()
    s = state()
    s.screen_lines = ('There is nothing here.',)
    assert [progress.advance(s) for _ in range(7)] == ['a'] * 4 + ['b', 'b', None]
    s.screen_lines = ('A new page.',)
    assert progress.advance(s) == 'a'
    progress.reset()
    assert progress.attempts == 0


def test_departure_is_offered_without_exhausting_npcs_or_tiles(owner):
    s = state()
    s.mechanics_verified = False
    sprite = NS(key='object:4', pixel_x=24*16, pixel_y=18*16)
    owner.strategy.observe(s, (sprite,), True)
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    tasks = candidates(s, owner.memory, terrain)
    assert {task['kind'] for task in tasks} >= {'talk', 'exit'}


def test_completed_npc_stays_completed_when_the_milestone_changes(owner):
    s = state()
    obs = owner.strategy.observations
    sprite = NS(key='object:1', pixel_x=24*16, pixel_y=18*16)
    obs.observe(s, (sprite,), overworld=True, milestone=6)
    npc = obs.data['npcs']['09:02/object:1']
    npc.update(status='talked', completed_milestone=6, pages=['A remembered clue.'])
    obs.observe(s, (sprite,), overworld=True, milestone=7)
    assert npc['status'] == 'talked'
    assert npc['pages'] == ['A remembered clue.']
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    assert all(task['id'] != npc['id'] for task in candidates(s, owner.memory, terrain))
