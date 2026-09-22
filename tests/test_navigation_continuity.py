"""Route execution, durable retracing history, and persistent map markers."""
from dataclasses import replace
from types import SimpleNamespace as NS
import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.discovery import observe_terrain
from jpp.agent.journey_knowledge import knowledge
from jpp.agent.journey_targets import paths, candidates
from jpp.agent.navigation_trace import record_step, record_target, unexhausted
from jpp.agent.route_execution import committed_heading
from jpp.gold97_collision import Gold97CollisionMap
from jpp.terrain_capture import OverworldSprite


def state(**changes):
    return NS(**(dict(map_group=3, map_number=13, x=1, y=1, map_width=8, map_height=4,
                     area_name='Boulder Mines 1F', in_battle=False, party=(), badge_ids=(),
                     map_exits=(), player_moving=False, screen_lines=(), screen_cursor=None,
                     battle=NS(kind='none', opponent=None), pokedex_caught_ids=(),
                     pokedex_species=(), mechanics_verified=False) | changes))


def terrain():
    return Gold97CollisionMap((3,13),8,4,bytes(32),tuple((x,y) for x in range(8) for y in range(4)))


@pytest.fixture
def owner(tmp_path):
    c=Gold97Controller('continuity', database=tmp_path/'agent.sqlite', vision_enabled=False)
    yield c
    c.close()


def target(cell=(6,1)):
    return dict(id='explore:corridor', kind='explore', cell=list(cell), map='03:0D', direction='', label='Explore')


def test_committed_corridor_holds_but_stops_at_target_turn_and_object(owner):
    s=state(x=2,player_moving=True,player_next_position=(3,1))
    owner.terrain=terrain()
    owner.strategy.target=target()
    owner.last=('03:0D',(1,1),'right')
    owner.held_action='right'
    owner._observe_move(s)
    assert owner.held_action=='right' and owner.last==('03:0D',(2,1),'right')
    owner._observe_move(s)  # Same coordinate while animation is unfinished.
    assert not owner.memory.map('03:0D')['blocked']
    assert committed_heading(owner,s,'right')
    s.x=6
    s.player_moving=False
    owner._observe_move(s)
    assert owner.held_action is None
    s.x=2
    owner.strategy.target=target((2,3))
    assert not committed_heading(owner,s,'right')
    owner.strategy.target=target()
    owner.strategy.data['npcs']['blocker'] = dict(id='blocker',map='03:0D',cell=[3,1],
                                               pages=[],status='pending',outcome='seen',visible=True)
    assert not committed_heading(owner,s,'right')


def test_accepted_single_step_does_not_queue_model_work(owner):
    class NoModel:
        def decide(self, branch):
            raise AssertionError('Committed single-option route must execute locally')
    owner.policy=NoModel()
    owner.strategy.target=target()
    owner.strategy.position=[1,1]
    owner.strategy.context=lambda s: {}
    action=owner._decide_step(state(),(),True,{'right':'Continue route'},None,'03:0D',(1,1),True)
    assert action=='right'
    assert owner.decision_future is None
    assert not owner.last_decision.request_made


def test_retrace_cost_prefers_alternative_without_forbidding_return(owner):
    s=state(x=1,y=1)
    for _ in range(6):
        record_step(owner.memory,'03:0D',(1,1),(2,1))
    routes=paths(s,owner.memory,terrain())
    assert routes[(4,1)] in {'up','down'}
    # A single corridor still permits a necessary return across a used edge.
    cells=bytearray([7]*32)
    for x in range(1,6): cells[8+x]=0
    corridor=Gold97CollisionMap((3,13),8,4,bytes(cells))
    assert paths(s,owner.memory,corridor)[(4,1)]=='right'
    owner.strategy.invalidate()
    assert owner.memory.map('03:0D')['movement_counts']
    assert len(owner.memory.map('03:0D')['trail'])==7


def test_exhausted_target_survives_replans_and_reopens_on_new_evidence(owner):
    t=target()
    record_target(owner.memory,t);record_target(owner.memory,t)
    owner.strategy.invalidate()
    assert not unexhausted(owner.memory,[t])
    owner.memory.world['discovery_revision']=1
    assert unexhausted(owner.memory,[t])


def test_partial_view_objects_survive_scroll_and_keep_last_seen_marker(owner):
    s=state()
    raw=replace(terrain(),visible_cells=((1,1),),entity_cells=((1,1),(2,1)))
    npc=OverworldSprite('object:8','03:0D',32,16,bytes(1024),kind='npc')
    owner.observe(s,(npc,),True,raw)
    obj=owner.strategy.data['npcs']['03:0D/object:8']
    assert obj['observed'] and obj['visible']
    assert len(owner.map_state.snapshot.entities)==1
    assert owner.map_state.snapshot.terrain.tile((2,1)) is None
    scroll=replace(raw,visible_cells=(),entity_cells=((1,1),(2,1)))
    owner.observe(s,(npc,),True,scroll)
    assert owner.map_state.snapshot.entities
    owner.observe(s,(),True,replace(raw,entity_cells=((1,1),)))
    assert owner.map_state.snapshot.objects[0]['observed']
    assert not owner.map_state.snapshot.objects[0]['visible']


def test_exact_checkpoint_memory_follows_path_alias_and_run_label(tmp_path):
    db=tmp_path/'agent.sqlite'
    source=Gold97Memory('original',db)
    checkpoint=tmp_path/'saved.state'
    source.world['route']={'completed':[1,2,3,4,5,6,7,8,9,10,11]}
    source.checkpoint(checkpoint)
    source.close()
    restored=Gold97Memory('new-label',db)
    try:
        assert restored.restore(checkpoint.parent/'.'/checkpoint.name)
        assert restored.world['route']['completed'][-1]==11
        assert not restored.restore(tmp_path/'different.state')
    finally:
        restored.close()


def test_missing_early_journey_history_does_not_disable_exploration(owner):
    s=state()
    owner.terrain=terrain()
    assert owner.route.now==1
    calls=[]
    owner.strategy.options=lambda state,ground: calls.append(state.area_name) or {}
    owner._navigate_step(s)
    assert calls==['Boulder Mines 1F']


def test_remembered_unknown_is_reobserved_not_forgotten(owner):
    s=state()
    owner.strategy.data['npcs']['unknown'] = dict(id='unknown',map='03:0D',cell=[3,1],
        pages=[],status='pending',outcome='seen',category='unknown',observed=True,visible=False)
    tasks=candidates(s,owner.memory,terrain())
    remembered=next(t for t in tasks if t['id']=='unknown')
    assert remembered['kind']=='explore'
    assert 'last-seen' in remembered['label']


def test_last_seen_marker_draws_even_when_terrain_tile_was_only_partly_visible(owner,monkeypatch):
    import pygame
    from jpp.live_map_grid import MapGrid
    from jpp.live_ui_colors import TEXT
    monkeypatch.setenv('SDL_VIDEODRIVER','dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER','dummy')
    pygame.init()
    try:
        s=state()
        raw=replace(terrain(),visible_cells=((1,1),),entity_cells=((1,1),(2,1)))
        npc=OverworldSprite('object:8','03:0D',32,16,bytes(1024),kind='npc')
        owner.observe(s,(npc,),True,raw)
        owner.observe(s,(),True,replace(raw,entity_cells=((1,1),)))
        ui=NS(canvas=pygame.Surface((80,40)),tiny=pygame.font.Font(None,12))
        MapGrid(ui).draw(owner.map_state.snapshot,pygame.Rect(0,0,80,40))
        assert ui.canvas.get_at((27,15))[:3]==TEXT
    finally:pygame.quit()


def test_ladder_is_reachable_but_cannot_be_used_as_corridor(owner):
    s = state(map_exits=((3, 1, '', 3, 14),))
    cells = bytearray([7] * 32)
    for x in range(1, 7):
        cells[8+x] = 0
    corridor = Gold97CollisionMap((3, 13), 8, 4, bytes(cells))
    reachable = paths(s, owner.memory, corridor)
    assert (3, 1) in reachable
    assert (4, 1) not in reachable
    # Arriving on a ladder must still allow stepping off it.
    s.x = 3
    assert (6, 1) in paths(s, owner.memory, corridor)


def test_checkpoint_journey_wins_over_stale_agent_route(owner, tmp_path, monkeypatch):
    from jpp.journey import Journey
    from jpp.live import _restore_agent
    monkeypatch.chdir(tmp_path)
    journey = Journey('continuity', database=tmp_path/'agent.sqlite')
    try:
        journey.route.completed.update(range(1, 12))
        journey.record_checkpoint('mine.state')
        owner.memory.world['route'] = {'completed': []}
        owner.memory.checkpoint('mine.state')
        journey.route.completed.clear()
        assert journey.restore_checkpoint(tmp_path/'mine.state')
        _restore_agent(owner, tmp_path/'mine.state', journey)
        assert journey.route.now == owner.route.now == 12
        assert owner.memory.world['route']['completed'] == list(range(1, 12))
        # An intentional undo in the checkpoint is authoritative too.
        journey.route.completed.remove(11)
        journey.record_checkpoint('undo.state')
        owner.memory.checkpoint('undo.state')
        assert journey.restore_checkpoint('undo.state')
        _restore_agent(owner, 'undo.state', journey)
        assert owner.route.now == 11
    finally:
        journey.close()


def test_viewpoint_reveals_unknown_across_wall(owner):
    from jpp.agent.discovery import ObservedTerrain, frontier_cells
    # Reachable floor has known walls beside it, but moving the camera can
    # reveal unknown ground beyond those walls.
    seen = frozenset((x, y) for x in range(2, 7) for y in range(4))
    t = ObservedTerrain((3, 13), 8, 4, bytes([7]*32), seen=seen)
    assert (3, 1) in frontier_cells({(3, 1): 'left'}, t, set())


def test_arrival_ladder_reentry_is_two_steps_and_budgeted(owner):
    from jpp.agent.discovery import ObservedTerrain
    from jpp.agent.journey_exits import exit_candidates
    from jpp.agent.journey_targets import target_options
    from jpp.agent.exploration_cycles import record_transition, filter_cycles
    s = state(x=3, y=1)
    t = ObservedTerrain((3,13), 8,4,bytes(32),
                        seen=frozenset((x,y) for x in range(8) for y in range(4)),
                        exits=((3,1,'',3,14),))
    choices = exit_candidates(s, owner.memory, paths(s, owner.memory, t), set(), t)
    selected = choices[0]
    assert selected['landing_return']
    action = next(iter(target_options(selected,s,owner.memory,t)))
    from jpp.agent.gold97_navigation import STEPS
    dx, dy = STEPS[action]
    s.x += dx; s.y += dy
    returning = next(iter(target_options(selected,s,owner.memory,t)))
    rx, ry = STEPS[returning]
    assert (s.x+rx,s.y+ry) == (3,1)
    for _ in range(3):
        record_transition(owner.memory,'03:0D',[3,1],'03:0E')
    assert not filter_cycles(choices,owner.memory)


def test_same_map_stair_is_recorded_without_active_plan(owner):
    owner.route.completed.update(range(1,12))
    first = state(x=1,y=1,map_exits=((1,1,'',3,13),))
    owner.strategy.observe(first,(),True)
    owner.strategy.target = None
    owner.strategy.observe(state(x=6,y=2,map_exits=((6,2,'',3,13),)),(),True)
    connection = owner.strategy.data['connections'][-1]
    assert connection['from'] == connection['to'] == '03:0D'
    assert connection['at'] == [1,1] and connection['arrival'] == [6,2]
    assert owner.memory.world['transition_budget']['counts']['03:0D:(1, 1)'] == 1


def test_committed_route_does_not_reverse_due_to_new_trail_cost(owner):
    from jpp.agent.journey_targets import target_options
    s = state(x=2,y=1)
    chosen = target((6,1))
    for _ in range(8):
        record_step(owner.memory,'03:0D',(2,1),(3,1))
    assert paths(s,owner.memory,terrain())[(6,1)] != 'right'
    assert target_options(chosen,s,owner.memory,terrain()) == {'right':'Explore'}
