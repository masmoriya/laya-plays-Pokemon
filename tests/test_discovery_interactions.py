"""Exploration, interaction evidence, and no-information transition budgets."""
from dataclasses import replace
from types import SimpleNamespace as NS
import pytest

from jpp.agent.discovery import observe_terrain
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.journey_knowledge import JourneyKnowledge, knowledge
from jpp.agent.journey_targets import candidates, paths
from jpp.agent.object_memory import classify, close_interaction, evidence_key, attempt, eligible
from jpp.agent.exploration_cycles import record_transition, filter_cycles
from jpp.agent.field_actions import FieldAction, experiments
from jpp.gold97_collision import Gold97CollisionMap
from jpp.terrain_capture import OverworldSprite


@pytest.fixture
def memory(tmp_path):
    m = Gold97Memory('discovery', tmp_path/'agent.sqlite')
    knowledge(m)
    yield m
    m.close()


def state(**kw):
    return NS(**(dict(map_group=3, map_number=13, x=1, y=1, map_width=12, map_height=8,
                     area_name='Boulder Mines 1F', in_battle=False, mechanics_verified=True,
                     party=(), badge_ids=(), map_exits=((2, 1, '', 3, 14), (10, 6, '', 3, 45)),
                     screen_lines=(), screen_cursor=None, player_facing='right') | kw))


def raw(visible=((1, 1), (2, 1), (1, 2), (2, 2))):
    return Gold97CollisionMap((3, 13), 12, 8, bytes(96), tuple(visible))


def sprite(index, x, y, kind='unknown'):
    return OverworldSprite(f'object:{index}', '03:0D', x*16, y*16, bytes(1024), kind=kind)


def test_fog_filters_terrain_paths_exits_and_persists(memory):
    s = state()
    terrain = observe_terrain(memory, s, raw(), True)
    assert terrain.tile((10, 6)) is None
    assert (10, 6) not in paths(s, memory, terrain)
    assert len(terrain.exits) == 1
    assert all(t['cell'] != [10, 6] for t in candidates(s, memory, terrain))
    memory.checkpoint('seen')
    later = observe_terrain(memory, s, raw(((10, 6),)), True)
    assert later.tile((1, 1)) == 0 and later.tile((10, 6)) == 0
    memory.restore('seen')
    restored = observe_terrain(memory, s, raw(()), False)
    assert restored.tile((10, 6)) is None and restored.tile((1, 1)) == 0
    assert not restored.visible


def test_items_and_frontiers_coexist_and_each_pickup_is_independent(memory):
    s = state(map_exits=())
    observer = JourneyKnowledge(memory)
    observer.observe(s, (sprite(1, 2, 1, 'item'), sprite(2, 2, 2, 'item')), overworld=True, milestone=12)
    terrain = observe_terrain(memory, s, raw(((1,1),(2,1),(1,2),(2,2),(1,3))), True)
    tasks = candidates(s, memory, terrain)
    assert len([t for t in tasks if t.get('category') == 'item']) == 2
    assert any(t['kind'] == 'explore' for t in tasks)
    item = observer.data['npcs']['03:0D/object:1']
    item['pages'] = ['LAYA put the GREAT BALL in', 'the BALL POCKET!']
    close_interaction(item)
    remaining = candidates(s, memory, terrain)
    assert not any(t['id'] == item['id'] for t in remaining)
    assert any(t['id'] == '03:0D/object:2' for t in remaining)


def test_manual_cart_clue_stays_unresolved_after_dialogue(memory):
    s = state()
    observer = JourneyKnowledge(memory)
    observer.observe(s, (sprite(4, 2, 1),), overworld=True, milestone=12)
    s.screen_lines = ('A POKéMON may be', 'able to move this.')
    for _ in range(5):
        observer.observe(s, (), overworld=False, milestone=12, prompt_visible=True)
    observer.observe(s, (sprite(4, 2, 1),), overworld=True, milestone=12)
    cart = observer.data['npcs']['03:0D/object:4']
    assert cart['outcome'] == 'unresolved'
    assert cart['status'] == 'pending' and cart['category'] == 'obstacle'
    assert not any('/interaction:' in n for n in observer.data['npcs'])
    memory.checkpoint('cart')
    cart['status'] = 'resolved'
    memory.restore('cart')
    assert knowledge(memory)['npcs'][cart['id']]['status'] == 'pending'


def test_contextual_attempt_limit_and_new_move(memory):
    npc = classify(dict(id='cart', map='03:0D', cell=[2,1], pages=['A POKEMON may be able to move this.']))
    s = state()
    s.badge_ids = ('johto_2',)
    context = evidence_key(s, npc)
    attempt(npc, context); attempt(npc, context)
    assert not eligible(npc, context)
    assert not experiments(s, npc)
    s.party = (NS(identity='one', moves=('STRENGTH',)),)
    assert eligible(npc, evidence_key(s, npc))
    assert experiments(s, npc) == [(0, 'STRENGTH')]


def test_transition_budget_survives_restart_and_resets_only_on_evidence(memory):
    t = dict(kind='exit', map='03:0D', cell=[2,1], destination_key='03:0E')
    for _ in range(3):
        record_transition(memory, '03:0D', [2,1], '03:0E')
    assert not filter_cycles([t], memory)
    memory.save()
    other = Gold97Memory(memory.run_id, memory.db.execute('PRAGMA database_list').fetchone()[2])
    try:
        assert not filter_cycles([t], other)
    finally:
        other.close()
    assert filter_cycles([{**t, 'retreat_reason': 'Heal injured party'}], memory)
    knowledge(memory)['clues'].append({'text':'New clue'})
    assert filter_cycles([t], memory)


def test_field_move_menu_execution_and_bounded_failure(memory):
    s = state(party=(NS(identity='one', moves=('STRENGTH',)),))
    s.badge_ids = ('johto_2',)
    s.strength_active = False
    npc = classify(dict(id='cart', cell=[2,1], pages=['A POKEMON may be able to move this.']))
    field = FieldAction()
    assert field.start(s, npc, memory)
    assert field.step(s, True) == 'start'
    s.screen_lines, s.screen_cursor = ('POKEMON',), (0,0)
    assert field.step(s, False) == 'a'
    s.party_cursor = 1
    assert field.step(s, False) == 'a'
    s.screen_lines = ('STRENGTH', 'CANCEL')
    assert field.step(s, False) == 'a'
    s.strength_active = True
    assert field.step(s, True) == 'right'
    field.step(s, True)
    assert not field.phase
    assert npc['outcome'] == 'unresolved'  # Selecting the move is not proof.
    s.strength_active = False
    assert field.start(s, npc, memory)
    for _ in range(125):
        field.step(s, False)
    assert field.phase is None
    assert not experiments(s, npc)


def test_observed_cart_movement_resolves_and_invalidates_blocks(memory):
    observer = JourneyKnowledge(memory)
    s = state()
    observer.observe(s, (sprite(4,2,1),), overworld=True, milestone=12)
    npc = observer.data['npcs']['03:0D/object:4']
    npc['pages'] = ['A POKEMON may be able to move this.']
    classify(npc)
    memory.map('03:0D')['blocked'] = [[[1,1], 'right']]
    observer.observe(s, (sprite(4,3,1),), overworld=True, milestone=12)
    assert npc['outcome'] == 'moved'
    assert not memory.map('03:0D')['blocked']
    assert classify(npc)['outcome'] == 'moved'


def test_visible_stairs_do_not_reveal_destination_and_distinct_stairs_survive(memory):
    s = state(map_exits=((1,2,'',3,14),(2,2,'',3,14)))
    terrain = observe_terrain(memory, s, raw(), True)
    assert all(e[3:] == (0,0) for e in terrain.exits)
    exits = [t for t in candidates(s, memory, terrain) if t['kind'] == 'exit']
    assert len(exits) == 2
    assert all(t['destination'] == 'Unknown destination' for t in exits)
    knowledge(memory)['connections'].append({'from':'03:0D','at':[1,2], 'to':'03:0E',
                                             'arrival':[4,5], 'direction':''})
    terrain = observe_terrain(memory, s, raw(), True)
    assert next(e for e in terrain.exits if e[:2] == (1,2))[3:] == (3,14)


def test_dashboard_masks_unseen_entities_goals_and_artwork(memory, monkeypatch):
    import pygame
    from jpp.live_map_state import LiveMapState
    from jpp.live_map import LiveMap
    from jpp.live_ui import LiveUI, SIZE
    from jpp.live_ui_colors import PANEL
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        s = state()
        ui.map_state.update(s, raw(), ready=True, overworld=True,
                            entities=(sprite(1,10,6),), destination=((3,13),(10,6)))
        assert not ui.map_state.snapshot.entities
        assert ui.map_state.snapshot.destination is None
        assert ui.map_state.snapshot.terrain.tile((10,6)) is None
        artwork = NS(tiles={'03:0D':{(20,12):(0,bytes([255,0,0,255])*64)}}, tile_revision=1)
        view = LiveMap(ui)
        view._area(s, artwork, pygame.Rect(0,0,240,160))
        assert tuple(view._terrain.get_at((160,96)))[:3] == tuple(PANEL)[:3]
    finally:
        pygame.quit()


@pytest.mark.parametrize('battle_result,outcome', [(0,'defeated'), (1,'seen'), (None,'seen')])
def test_trainer_started_is_not_trainer_defeated(memory, battle_result, outcome):
    observer = JourneyKnowledge(memory)
    s = state()
    observer.observe(s, (sprite(8,2,1),), overworld=True, milestone=12)
    observer.interacted('03:0D/object:8')
    s.in_battle = True
    observer.observe(s, (), overworld=False, milestone=12)
    s.in_battle, s.battle_result = False, battle_result
    observer.observe(s, (sprite(8,2,1),), overworld=True, milestone=12)
    assert observer.data['npcs']['03:0D/object:8']['outcome'] == outcome


def test_new_item_releases_failed_experiment_but_not_repeated_observation(memory):
    npc = classify(dict(id='cart', cell=[2,1], pages=[]))
    s = state()
    context = evidence_key(s, npc, memory)
    attempt(npc, context); attempt(npc, context)
    assert not eligible(npc, evidence_key(s, npc, memory))
    knowledge(memory)['npcs']['item'] = dict(id='item', cell=[4,1], map='03:0D',
                                           pages=[], outcome='collected', status='resolved')
    assert eligible(npc, evidence_key(s, npc, memory))


def test_known_traversed_paths_survive_without_inventing_seen_terrain(memory):
    memory.move_result('03:0D', (1,1), 'right', (2,1))
    s = state()
    terrain = observe_terrain(memory, s, raw(((1,1),)), True)
    assert terrain.tile((2,1)) is None
    assert (2,1) in paths(s, memory, terrain)
    assert (3,1) not in paths(s, memory, terrain)


def test_legacy_navigation_exclusion_does_not_hide_newly_classified_item(memory):
    from jpp.agent.experience import target_key
    s = state(map_exits=())
    observer = JourneyKnowledge(memory)
    observer.observe(s, (sprite(2,2,1,'item'),), overworld=True, milestone=12)
    terrain = observe_terrain(memory, s, raw(), True)
    original = next(t for t in candidates(s, memory, terrain) if t['id']=='03:0D/object:2')
    excluded = {original['id'], target_key(original)}
    assert any(t['id']==original['id'] for t in candidates(s, memory, terrain, excluded=excluded))
    npc = observer.data['npcs'][original['id']]
    context = evidence_key(s, npc, memory)
    attempt(npc, context, 'approach'); attempt(npc, context, 'approach')
    assert not any(t['id']==original['id'] for t in candidates(s, memory, terrain, excluded=excluded))


def test_location_names_and_refusals_are_not_completion_evidence():
    npc = classify(dict(status='pending', pages=['Welcome to Boulder Mines!']))
    close_interaction(npc)
    assert npc['category'] == 'unknown' and npc['outcome'] == 'conversed'
    item = classify(dict(category='item', status='pending',
                         pages=["You cannot put the item in your pocket."]))
    close_interaction(item)
    assert item['outcome'] == 'unresolved'
