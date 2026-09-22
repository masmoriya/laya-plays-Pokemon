"""Player training preference changes battles and recovery, retaining the journey."""
from dataclasses import replace

from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_training import Training
from test_gold97_readiness import mon, state


def test_training_toggle_persists_without_changing_automatic_budget(tmp_path):
    db = tmp_path / 'training.sqlite'
    memory = Gold97Memory('training', database=db)
    training = Training(memory)
    assert not training.enabled
    assert training.toggle()
    training.data['exhausted'] = True
    memory.save()
    restored = Gold97Memory('training', database=db)
    assert Training(restored).enabled
    assert not Training(restored).toggle()
    memory.db.close()
    restored.db.close()


def test_training_fights_with_one_capable_partner_and_off_restores_run(tmp_path):
    controller = Gold97Controller('training', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state((mon(level=20, stats=(45,) * 5), mon(slot=2, hp=0)),
                  mon(level=8, hp=12, stats=(15,) * 5))
        goal = controller.route.now
        assert BattleExecutor._plan(controller, s).kind == 'escape'
        controller.training.toggle()
        assert BattleExecutor._plan(controller, s).kind == 'move'
        controller.training.toggle()
        assert BattleExecutor._plan(controller, s).kind == 'escape'
        assert controller.route.now == goal
    finally:
        controller.close()


def test_training_chooses_lower_level_grass_partner_against_rock():
    strong = mon(level=25, stats=(60,) * 5)
    grass = mon(slot=2, species='KURSTRAW', level=12, types=('GRASS',),
                moves=('VINE WHIP',), stats=(35,) * 5)
    foe = mon(species='GEODUDE', level=8, types=('ROCK', 'GROUND'),
              hp=25, max_hp=25, stats=(15,) * 5)
    s = state((strong, grass), foe)
    policy = Gold97BattleStrategy()
    action = policy.plan(s, intent='practice')
    assert (action.kind, action.target) == ('switch', 1)
    s.active_slot = 1
    s.battle = replace(s.battle, active=grass)
    s.battle_participants = 3
    assert policy.plan(s, intent='practice').kind == 'move'
    s.switch_allowed = False
    s.active_slot = 0
    s.battle = replace(s.battle, active=strong)
    assert policy.plan(s, intent='practice').kind != 'switch'


def test_training_runs_when_no_viable_fighter():
    s = state((mon(hp=1, stats=(10,) * 5),), mon(level=40, stats=(80,) * 5))
    assert Gold97BattleStrategy().plan(s, intent='practice').kind == 'escape'


def test_training_heals_fainted_partner_then_resumes_same_milestone(tmp_path):
    controller = Gold97Controller('heal', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state((mon(level=20), mon(slot=2, hp=0)))
        goal = controller.route.now
        assert controller._recovery_action(s, overworld=True) is None
        controller.training.toggle()
        controller._service_route = lambda *args, **kwargs: 'left'
        assert controller._recovery_action(s, overworld=True) == 'left'
        assert controller.recovery['reason'] == 'healing'
        s.area_name, s.map_group, s.map_number = 'Pagota Pokemon Center', 10, 14
        s.party = (mon(level=20), mon(slot=2))
        controller._recovery_action(s, overworld=True)
        assert controller.recovery['exit']
        s.area_name, s.map_group, s.map_number = 'Brass Tower', 3, 2
        assert controller._recovery_action(s, overworld=True) is None
        assert controller.recovery is None
        assert controller.training.enabled
        assert controller.route.now == goal
    finally:
        controller.close()
