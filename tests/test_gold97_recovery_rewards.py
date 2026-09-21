from concurrent.futures import Future
from types import SimpleNamespace as NS

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_playback import Playback
from jpp.agent.journey_knowledge import JourneyKnowledge, knowledge
from jpp.agent.journey_targets import paths
from jpp.gold97_collision import Gold97CollisionMap


def state(**kwargs):
    values = dict(map_group=9,map_number=2,x=1,y=1,map_width=6,map_height=6,
                  in_battle=False,screen_lines=(),area_name='Pagota City',party=(),
                  badge_ids=(),battle=NS(kind='none',active=None,opponent=None))
    values.update(kwargs)
    return NS(**values)


def test_battle_aftermath_and_garbage_never_complete_conversation(tmp_path):
    memory=Gold97Memory('run',tmp_path/'test.sqlite')
    observer=JourneyKnowledge(memory)
    sprite=NS(key='object:1',pixel_x=32,pixel_y=16)
    s=state()
    observer.observe(s,(sprite,),overworld=True,milestone=6)
    key=next(iter(observer.data['npcs']))
    observer.interacted(key)
    s.screen_lines=('99999999999999999999',)
    for _ in range(5):observer.observe(s,(),overworld=False,milestone=6)
    assert not observer.data['clues']
    s.in_battle=True
    observer.observe(s,(),overworld=False,milestone=6)
    s.in_battle=False;s.screen_lines=('Got away safely.',)
    for _ in range(5):observer.observe(s,(),overworld=False,milestone=6)
    observer.observe(s,(sprite,),overworld=True,milestone=6)
    assert not observer.data['clues']
    assert observer.data['npcs'][key]['status']=='pending'
    memory.close()


def test_legacy_invalid_evidence_archived_and_stale_npc_does_not_block(tmp_path):
    memory=Gold97Memory('run',tmp_path/'test.sqlite')
    data=knowledge(memory);data['version']=1
    data['clues']=[{'id':'bad','text':'9999999999999'},{'id':'good','text':'Bill lives in this town.'}]
    data['npcs']={'npc':{'id':'npc','map':'09:02','cell':[2,1], 'pages':['Got away safely.'],
                        'status':'talked','attempts':2}}
    data=knowledge(memory)
    assert data['archive'][-1]['clues'][0]['id']=='bad'
    assert data['clues'][0]['id']=='good'
    assert data['npcs']['npc']['status']=='pending'
    terrain=Gold97CollisionMap((9,2),6,6,bytes(36))
    assert (2,1) in paths(state(),memory,terrain)
    memory.close()


def test_manual_observation_records_connections_without_play(tmp_path):
    controller=Gold97Controller('run',database=tmp_path/'test.sqlite',vision_enabled=False)
    try:
        controller.manual_pause()
        s=state();controller.observe(s,(),True)
        s=state(map_number=7,x=5,y=7);controller.observe(s,(),True)
        assert controller.strategy.data['connections'][0]['to']=='09:07'
        assert not controller.playback.requested
    finally:controller.close()


def test_play_intent_survives_outage_restore_and_manual_pause_wins(tmp_path):
    memory=Gold97Memory('run',tmp_path/'test.sqlite');play=Playback(memory)
    play.request(True);memory.checkpoint('before')
    play.waiting('offline');assert play.requested
    assert Playback(memory).requested
    memory.restore('before');assert Playback(memory).requested
    play.request(False);assert not Playback(memory).requested
    memory.close()


def test_luna_failure_falls_back_without_pause_and_off_stays_off(tmp_path):
    controller=Gold97Controller('run',database=tmp_path/'test.sqlite',vision_enabled=False)
    try:
        strategy=controller.strategy;strategy.data['enabled']=True
        strategy.future=Future();strategy.future.set_exception(RuntimeError('outage'))
        strategy.payload={'candidates':[]}
        s=state();controller.route.completed.update(range(1,6))
        terrain=Gold97CollisionMap((9,2),6,6,bytes(36))
        strategy.observe(s,(),True)
        strategy.future=Future();strategy.future.set_exception(RuntimeError('outage'))
        assert strategy.options(s,terrain)
        assert strategy.status=='Laya fallback' and not controller.paused
        strategy.toggle();strategy.retry_at=0
        assert not strategy.use_luna
    finally:controller.close()


def test_no_interaction_text_and_partial_pages_are_not_clues(tmp_path):
    memory=Gold97Memory('run',tmp_path/'test.sqlite')
    observer=JourneyKnowledge(memory); s=state()
    observer.observe(s,(NS(key='object:1',pixel_x=32,pixel_y=16),),overworld=True,milestone=6)
    observer.interacted(next(iter(observer.data['npcs'])))
    for page in ('There  nothing here', 'There is nothing here', 'Bill lives in'):
        s.screen_lines=(page,)
        for _ in range(4): observer.observe(s,(),overworld=False,milestone=6)
    assert not observer.data['clues']
    s.screen_lines=('Bill lives in this town.',)
    for _ in range(14): observer.observe(s,(),overworld=False,milestone=6)
    assert len(observer.data['clues'])==1
    memory.close()


def test_manual_pause_cancels_pending_actions_and_owns_no_new_transfer(tmp_path):
    c=Gold97Controller('run',database=tmp_path/'test.sqlite',vision_enabled=False)
    try:
        c.resume();c.decision_future=Future();c.strategy.future=Future()
        tactical, strategic = c.decision_future, c.strategy.future
        c.party_reorder.phase='switch';c.roster_service.target=((1,1),'up')
        c.held_action='right';c.manual_pause()
        assert tactical.cancelled() and strategic.cancelled()
        assert c.held_action is None and c.party_reorder.phase=='close'
        assert c.roster_service.target is None and not c.playback.requested
    finally:c.close()


def test_provider_retry_resumes_only_with_retained_play_intent(tmp_path):
    c=Gold97Controller('run',database=tmp_path/'test.sqlite',vision_enabled=False)
    try:
        c.resume();c.pause('Laya unavailable: transient error')
        assert c.playback.requested and c.provider_health=='unavailable'
        c.provider_health_future=Future();c.provider_health_future.set_result({'status':'ok'})
        c._poll_provider_health()
        assert not c.paused and c.playback.status=='playing'
        c.pause('Laya unavailable: transient error');c.manual_pause()
        c.provider_health_future=Future();c.provider_health_future.set_result({'status':'ok'})
        c._poll_provider_health()
        assert not c.playback.requested and c.playback.summary()['status']=='manually paused'
    finally:c.close()
