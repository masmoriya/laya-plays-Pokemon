from dataclasses import replace
from types import SimpleNamespace as NS

from jpp.decode import Mon, Battle
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_rewards import RewardLedger, level_exp
from jpp.route_progress import RouteProgress


def mon(**kw):
    return replace(Mon(1, 'TANGTRIP', 8, 26, 26, 'none', ('GRASS',),
                       species_id=1, identity='ot-dvs-caught', experience=512, growth_rate=0), **kw)


def state(party, battle=False, boxes=(), caught=()):
    return NS(party=party, box_roster=boxes, in_battle=battle, mechanics_verified=True,
              active_slot=0 if battle else None, battle=Battle('wild' if battle else 'none', party[0] if party else None, None),
              pokedex_caught_ids=caught, pokedex_species=('UNKNOWN', 'TANGTRIP', 'VOLBEAR'))


def test_xp_high_water_survives_boxing_restore_and_restart(tmp_path):
    mem = Gold97Memory('run', tmp_path / 'run.sqlite')
    ledger, route = RewardLedger(mem), RouteProgress()
    old, leveled = mon(), mon(level=9, experience=729)
    ledger.observe(state((old,)), route)
    mem.checkpoint('before')
    ledger.observe(state((old,), True), route)
    ledger.observe(state((leveled,), True), route)
    assert ledger.data['total'] == 20
    for _ in range(3): ledger.observe(state((leveled,), True), route)
    ledger.observe(state((), boxes=(leveled,)), route)
    assert ledger.data['total'] == 20
    mem.restore('before')
    ledger.observe(state((old,)), route)
    ledger = RewardLedger(mem)
    ledger.observe(state((old,), True), route)
    ledger.observe(state((leveled,), True), route)
    assert ledger.data['total'] == 20
    mem.close()


def test_ambiguous_individuals_and_nonbattle_gains_are_not_rewarded(tmp_path):
    mem = Gold97Memory('run', tmp_path / 'run.sqlite')
    ledger, route = RewardLedger(mem), RouteProgress()
    first = mon()
    ledger.observe(state((first, first)), route)
    ledger.observe(state((replace(first, experience=729, level=9), first), True), route)
    assert ledger.data['total'] == 0
    ledger.observe(state((mon(level=10, experience=1000),)), route)
    assert ledger.data['total'] == 0
    mem.close()


def test_capture_evolution_and_verified_milestone_only_once(tmp_path):
    mem = Gold97Memory('run', tmp_path / 'run.sqlite')
    ledger, route = RewardLedger(mem), RouteProgress()
    first = mon()
    ledger.observe(state((first,)), route)
    ledger.observe(state((first,), True), route)
    route.confirm()  # Manual story assertions do not award points.
    evolved = replace(first, species='VOLBEAR', species_id=2)
    ledger.observe(state((evolved,), True, caught=(2,)), route)
    assert ledger.data['total'] == 25
    route.completed.add(6)
    ledger.observe(state((evolved,), caught=(2,)), route)
    assert ledger.data['total'] == 125
    ledger.observe(state((evolved,), caught=(2,)), route)
    assert ledger.data['total'] == 125
    mem.close()


def test_exp_share_earns_without_switching_and_reordering_is_free(tmp_path):
    mem = Gold97Memory('run', tmp_path / 'run.sqlite')
    ledger, route = RewardLedger(mem), RouteProgress()
    first, trainee = mon(identity='first'), mon(identity='second', held_item='Exp Share')
    ledger.observe(state((first, trainee)), route)
    ledger.observe(state((first, trainee), True), route)
    ledger.observe(state((first, replace(trainee, experience=534)), True), route)
    assert ledger.data['total'] == 1
    ledger.observe(state((trainee, first)), route)
    assert ledger.data['total'] == 1
    mem.close()


def test_growth_matches_observed_cartridge_party():
    assert level_exp(20, 3) == 5460
    assert level_exp(8, 0) == 512
    assert level_exp(8, 3) == 314


def test_postbattle_nonbattle_xp_is_not_inferred_as_battle_earnings(tmp_path):
    mem = Gold97Memory('run', tmp_path/'run.sqlite')
    ledger, route = RewardLedger(mem), RouteProgress()
    original = mon()
    ledger.observe(state((original,)), route)
    ledger.observe(state((original,), True), route)
    ledger.observe(state((original,)), route)
    ledger.observe(state((mon(level=9,experience=729),)), route)
    assert ledger.data['total']==0
    mem.close()


def test_capture_requires_wild_target_and_ball_consumption(tmp_path):
    mem=Gold97Memory('run',tmp_path/'run.sqlite')
    ledger,route=RewardLedger(mem),RouteProgress()
    a=mon();s=state((a,));s.poke_ball_count=5
    ledger.observe(s,route)
    s=state((a,),True);s.poke_ball_count=5
    s.battle=Battle('wild',a,mon(species='VOLBEAR',species_id=2,identity='foe'))
    ledger.observe(s,route)
    s.pokedex_caught_ids=(2,)
    ledger.observe(s,route)
    assert ledger.data['total']==0
    s.poke_ball_count=4
    ledger.observe(s,route)
    assert ledger.data['total']==25
    ledger.observe(s,route)
    assert ledger.data['total']==25
    mem.close()
