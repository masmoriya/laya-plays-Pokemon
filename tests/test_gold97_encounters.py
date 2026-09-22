from dataclasses import replace
from types import SimpleNamespace as NS

from jpp.decode import Mon, Battle
from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_encounters import capture_move
from jpp.agent.gold97_training import Training
from jpp.agent.gold97_memory import Gold97Memory
from jpp.route_progress import RouteProgress


def mon(**kw):
    return replace(Mon(1, 'VOLBEAR', 20, 60, 60, 'none', ('FIRE',),
                       moves=('EMBER', 'TACKLE'), pp=(25, 30), species_id=156,
                       stats=(45,40,40,45,40), stages=(0,)*7), **kw)


def state(active, foe, **kw):
    values = dict(battle=Battle('wild', active, foe), party=(active,), active_slot=0,
                  poke_ball_count=5, pokedex_caught_ids=(), potion_count=0,
                  mechanics_verified=True, in_battle=True, frame_number=0)
    values.update(kw)
    return NS(**values)


def test_ordinary_wild_is_fought_and_eligible_species_is_captured():
    active, foe = mon(), mon(species='RATTATA', species_id=19, hp=8, max_hp=20, level=8)
    policy = Gold97BattleStrategy()
    party = (active, mon(slot=2))
    assert policy.plan(state(active, foe, party=party)).kind == 'move'
    foe = replace(foe, species='TANGTRIP', species_id=1)
    assert policy.plan(state(active, foe, party=party)).kind == 'ball'
    assert policy.plan(state(active, foe, party=party, poke_ball_count=0)).kind == 'move'


def test_static_encounter_never_recaptures_owned_species():
    active = mon()
    foe = mon(species='TANGTRIP', species_id=1, hp=8, max_hp=20, level=8)
    policy = Gold97BattleStrategy()
    policy.static_capture = True

    result = policy.plan(state(active, foe, pokedex_caught_ids=(1,)))

    assert result.kind != 'ball'


def test_training_switch_requires_surviving_replacement():
    weak = mon(species='HOPPIP', species_id=187, level=8, hp=26, max_hp=26,
               stats=(15,15,15,15,15))
    strong = mon()
    foe = replace(weak, species='RATTATA', types=('NORMAL',), moves=('TACKLE',), pp=(30,))
    result = Gold97BattleStrategy().plan(state(weak, foe, party=(weak,strong,mon(slot=3))), intent='training')
    assert result.kind == 'switch' and result.target == 1
    result = Gold97BattleStrategy().plan(state(replace(weak,hp=1), foe, party=(replace(weak,hp=1),)))
    assert result.kind == 'escape'


def test_capture_avoids_lethal_moves_and_status_repetition():
    active = mon(moves=('SLEEP POWDER','TACKLE'), pp=(10,30))
    foe = mon(species='TANGTRIP', hp=10, max_hp=26)
    assert capture_move(active, foe).target == 0
    assert capture_move(active, replace(foe, status='sleep', hp=2)) is None
    assert capture_move(mon(), replace(foe, status='sleep')) is None


def test_training_budget_uses_emulated_time_and_fresh_evidence(tmp_path):
    memory = Gold97Memory('run', tmp_path/'run.sqlite')
    training, route = Training(memory), RouteProgress()
    s = state(mon(), mon())
    training.observe(s, route)
    training.data['active'] = True
    s.frame_number = 18000
    training.observe(s, route)
    assert training.data['exhausted']
    s.frame_number = 0  # Rewind alone must not rearm the budget.
    training.observe(s, route)
    assert training.data['exhausted']
    route.completed.add(1)
    training.observe(s, route)
    assert not training.data['exhausted']
    memory.close()


def test_training_only_preempts_journey_after_verified_trainer_loss(tmp_path):
    memory = Gold97Memory('run', tmp_path/'run.sqlite')
    training = Training(memory)
    weak, strong = mon(level=8), mon(level=20)
    training.levels = [20]
    s = state(weak, strong, party=(weak, strong), in_battle=False)
    assert not training.required(s)
    training.data['readiness_failure'] = {'species': 'FALKNER'}
    assert training.required(s)
    training.data['exhausted'] = True
    assert not training.required(s)
    memory.close()
