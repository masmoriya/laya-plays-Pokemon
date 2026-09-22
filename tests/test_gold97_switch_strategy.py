"""Regressions for wild matchup/training oscillation and travel lead selection."""
from dataclasses import replace
from types import SimpleNamespace as NS

from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_training import Training
from jpp.agent.gold97_memory import Gold97Memory
from test_gold97_encounters import mon, state
from test_gold97_tactics import owner


def geodude():
    return mon(species='GEODUDE', species_id=74, level=12, hp=45, max_hp=45,
               types=('ROCK', 'GROUND'), moves=('TACKLE',), pp=(30,),
               stats=(25, 45, 15, 15, 20))


def partners():
    fire = mon(level=25, moves=('EMBER',), pp=(25,))
    grass = mon(slot=2, species='TANGELA', species_id=114, level=20,
                types=('GRASS',), moves=('ABSORB',), pp=(20,))
    return fire, grass


def test_geodude_matchup_switches_once_then_tangela_attacks():
    fire, grass = partners()
    planner = Gold97BattleStrategy()
    s = state(fire, geodude(), party=(fire, grass))
    assert planner.plan(s).target == 1
    assert planner.plan(s).kind == 'switch'
    s.active_slot = 1
    s.battle = replace(s.battle, active=grass)
    # Even a restored fight without executor history must not train level 20.
    assert planner.plan(s).kind == 'move'
    assert planner.plan(s).target == 0


def test_executor_confirms_entry_then_uses_grass_move():
    fire, grass = partners()
    s = state(fire, geodude(), party=(fire, grass), battle_menu_kind='command',
              battle_menu_cursor=(2, 1), screen_lines=(), screen_cursor=None)
    ex, control = BattleExecutor(), owner()
    assert ex.step(control, s) == 'a'
    s.battle_menu_kind, s.battle_menu_cursor = 'party', (1, 2)
    assert ex.step(control, s) == 'a'
    assert not control.battle_strategy.switched_from
    s.active_slot = 1
    s.battle = replace(s.battle, active=grass)
    s.battle_menu_kind, s.battle_menu_cursor = 'command', (1, 1)
    assert ex.step(control, s) == 'a'
    assert control.battle_strategy.switched_from == {0}
    assert ex.action.kind == 'move'
    s.battle_menu_kind = 'moves'
    assert ex.step(control, s) == 'a'


def test_baby_with_easy_matchup_attacks_without_handoff():
    _, grass = partners()
    baby = replace(grass, level=8)
    fire, _ = partners()
    s = state(baby, replace(geodude(), hp=1), party=(baby, fire))
    assert Gold97BattleStrategy().plan(s).kind == 'move'


def test_training_handoff_is_not_repeated_after_confirmed_switch():
    baby = mon(level=5, stats=(8, 20, 8, 8, 20))
    strong = mon(level=9)
    foe = replace(geodude(), types=('NORMAL',), hp=40)
    planner = Gold97BattleStrategy()
    s = state(baby, foe, party=(baby, strong))
    assert planner.plan(s).kind == 'switch'
    planner.record_switch(0)
    s.active_slot = 1
    s.battle = replace(s.battle, active=strong)
    assert planner.plan(s).kind == 'move'
    planner.reset()
    assert not planner.switched_from


def test_safety_can_return_to_previous_battler():
    fire, grass = partners()
    planner = Gold97BattleStrategy()
    planner.record_switch(0)
    injured = replace(grass, hp=1)
    s = state(injured, geodude(), party=(fire, injured), active_slot=1)
    assert planner.plan(s).kind == 'switch'
    assert planner.plan(s).target == 0


def test_travel_selects_baby_without_trainer_loss_and_avoids_unsafe_areas(tmp_path):
    memory = Gold97Memory('switch', tmp_path / 'switch.sqlite')
    training = Training(memory)
    fire, grass = partners()
    baby = mon(slot=3, level=5)
    s = state(fire, geodude(), party=(fire, grass, baby), in_battle=False,
              area_name='Route 103', x=2, y=2)
    terrain = NS(tile=lambda cell: 0x10)
    assert training.travel_lead(s, terrain) == 2
    assert not training.required(s)
    assert training.travel_lead(s, NS(tile=lambda cell: 0)) is None
    s.area_name = 'Gym'
    assert training.travel_lead(s, terrain) is None
    s.area_name = 'Route 103'
    s.party = (replace(fire, hp=0), replace(grass, hp=0), baby)
    assert training.travel_lead(s, terrain) is None
    memory.close()


def test_controller_reorders_baby_before_continuing_route(tmp_path):
    from jpp.agent.controller_decision import DecisionExecution
    from jpp.agent.gold97_party import PartyReorder
    memory = Gold97Memory('lead', tmp_path / 'lead.sqlite')
    fire, _ = partners()
    baby = mon(slot=2, level=5, identity='baby')
    fire = replace(fire, identity='fire')
    s = state(fire, geodude(), party=(fire, baby), in_battle=False,
              area_name='Route 103', x=2, y=2, map_group=1, map_number=1,
              screen_lines=(), screen_cursor=None)
    controller = NS(training=Training(memory), party_reorder=PartyReorder(),
                    terrain=NS(tile=lambda cell: 0x10), route=NS(now=3),
                    _location=lambda state: ('01:01', (2, 2)))
    assert DecisionExecution._navigate_step(controller, s) == 'start'
    assert controller.party_reorder.target == 1
    memory.close()


def test_prior_participation_prevents_training_handoff():
    from jpp.agent.gold97_encounters import training_handoff
    baby = mon(level=5, stats=(8, 20, 8, 8, 20))
    fire, _ = partners()
    s = state(baby, geodude(), party=(baby, fire), battle_participants=3)
    assert not training_handoff(Gold97BattleStrategy(), s, 1)
    s.battle_participants = 1
    assert training_handoff(Gold97BattleStrategy(), s, 1)
    s.battle = replace(s.battle, active=replace(baby, held_item='EXP SHARE'))
    assert not training_handoff(Gold97BattleStrategy(), s, 1)


def test_matchup_history_blocks_voluntary_return_but_not_forced_replacement():
    fire, grass = partners()
    planner = Gold97BattleStrategy()
    planner.record_switch(1)
    s = state(fire, geodude(), party=(fire, grass))
    assert planner.plan(s).kind == 'move'
    s.battle = replace(s.battle, active=replace(fire, hp=0))
    assert planner.plan(s, forced=True).target == 1
