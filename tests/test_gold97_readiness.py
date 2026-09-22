"""Journey progress takes priority over optional combat and individual damage."""
from dataclasses import replace, asdict
from types import SimpleNamespace as NS

import pytest

from jpp.decode import Mon, Battle
from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_readiness import assess_party, capable, affordable_fight
from jpp.agent.gold97_services import needs_healing


def mon(**kw):
    values = dict(slot=1, species='KOTORA', level=16, hp=56, max_hp=56,
                  status='none', types=('ELECTRIC',), moves=('TACKLE',), pp=(30,))
    values.update(kw)
    return Mon(**values)


def state(party, foe=None):
    return NS(party=party, battle=Battle('wild' if foe else 'none', party[0], foe),
              in_battle=foe is not None, active_slot=0, area_name='Brass Tower',
              map_group=3, map_number=2, map_width=20, map_height=20, x=2, y=1,
              poke_ball_count=5, pokedex_caught_ids=(), potion_count=0,
              battle_menu_kind='command', battle_menu_cursor=(1, 1),
              screen_lines=(), screen_cursor=None)


def pictured_party():
    return (mon(), mon(slot=2, species='VOLBEAR', level=25, hp=30, max_hp=72),
            mon(slot=3, species='KURSTRAW', level=7, hp=24, max_hp=24),
            mon(slot=4, species='TYROGUE', level=5, hp=19, max_hp=19),
            mon(slot=5, species='CHIX', level=8, hp=22, max_hp=22),
            mon(slot=6, species='TANGELA', level=20, hp=62, max_hp=62))


def test_pictured_party_continues_and_uses_capable_travel_lead(tmp_path):
    controller = Gold97Controller('readiness', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state(pictured_party())
        controller.training.local_opponents[s.area_name] = [mon(level=12)]
        goal = controller.route.now
        assert needs_healing(s)  # Individual recovery remains separate.
        readiness = controller.training.readiness(s)
        assert readiness.capable_slots == (0, 5)
        assert not readiness.needs_detour
        assert controller._recovery_action(s, overworld=True) is None
        assert controller.recovery is None
        assert controller.training.travel_lead(s, None) == 5
        assert controller.route.now == goal
    finally:
        controller.close()


def test_only_tyrogue_left_triggers_recovery(tmp_path):
    controller = Gold97Controller('last-partner', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state((mon(hp=0), mon(species='TYROGUE', level=5, hp=19, max_hp=19)))
        controller.training.local_opponents[s.area_name] = [mon(level=12)]
        assert controller.training.readiness(s).needs_detour
        controller._service_route = lambda *args, **kw: 'left'
        assert controller._recovery_action(s, overworld=True) == 'left'
        assert controller.recovery['reason'] == 'healing'
    finally:
        controller.close()


@pytest.mark.parametrize('change', [dict(hp=0), dict(hp=20), dict(status='poison'),
                                   dict(pp=(0,)), dict(moves=('GROWL',)), dict(species='EGG')])
def test_unusable_partners_do_not_count_as_reserves(change):
    s = state((mon(), mon(**change)))
    assert assess_party(s).capable_slots == (0,)
    assert assess_party(s).conserve


def test_matchup_and_level_fallback():
    foe = mon(level=12, types=('GRASS',), stats=(30, 30, 30, 30, 30))
    strong = mon(types=('FIRE',), moves=('EMBER',), stats=(40, 40, 40, 40, 40))
    assert capable(strong, foe)
    assert not capable(mon(level=5), replace(foe, stats=()))
    assert not capable(mon(moves=('TACKLE',)), mon(types=('GHOST',)))
    assert not capable(strong, replace(foe, level=40, stats=(100,)*5))


def test_different_partners_can_cover_different_local_matchups():
    ground = mon(moves=('EARTHQUAKE',), types=('GROUND',))
    normal = mon(moves=('TACKLE',), types=('NORMAL',))
    foes = (mon(level=12, types=('FLYING',)), mon(level=12, types=('GHOST',)))
    ready = assess_party(state((ground, normal)), threats=foes)
    assert ready.capable_slots == (0, 1)
    assert not ready.needs_detour


def test_last_capable_partner_runs_even_from_easy_or_collectible_foe():
    foe = mon(species='TANGTRIP', species_id=1, level=8, hp=10)
    s = state((mon(level=20), mon(level=5)), foe)
    assert Gold97BattleStrategy().plan(s).kind == 'escape'


def test_safe_optional_battle_and_expensive_switch():
    foe = mon(level=8, hp=12, max_hp=24, types=('NORMAL',), stats=(15,)*5)
    strong = mon(level=20, stats=(45,)*5)
    assert Gold97BattleStrategy().plan(state((strong, replace(strong, slot=2)), foe)).kind == 'move'
    assert not affordable_fight(mon(hp=35, stats=(25,)*5), mon(stats=(30,)*5), switching=True)


def test_training_lead_is_separate_from_travel_and_local_threats(tmp_path):
    controller = Gold97Controller('leads', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state((mon(level=5), mon(slot=2, level=20)))
        controller.training.local_opponents['Other map'] = [mon(level=60)]
        assert controller.training.travel_lead(s, None) == 1
        assert controller.training.lead(s) == 0
        assert not controller.training.readiness(s).needs_detour
    finally:
        controller.close()


def test_fully_healed_underlevel_team_does_not_loop_at_center(tmp_path):
    controller = Gold97Controller('levels', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state((mon(level=5),))
        controller.training.local_opponents[s.area_name] = [mon(level=12)]
        assert controller.training.readiness(s).needs_detour
        assert controller._recovery_action(s, overworld=True) is None
        assert controller.recovery is None
    finally:
        controller.close()


def test_trainer_and_explicit_escape_restriction_are_fought():
    s = state((mon(),), mon(level=8))
    policy = Gold97BattleStrategy()
    s.battle = replace(s.battle, kind='trainer')
    assert policy.plan(s).kind != 'escape'
    s.battle = replace(s.battle, kind='wild')
    s.escape_allowed = False
    assert policy.plan(s).kind != 'escape'


def test_cartridge_escape_restrictions_are_not_failed_rolls():
    from jpp.gold97_battle_state import battle_restrictions
    mem = bytearray(0x10000)
    assert battle_restrictions(mem, 'wild', True) == (True, True)
    mem[0xC671] = 0x80
    assert battle_restrictions(mem, 'wild', True) == (False, False)
    mem[0xC671], mem[0xC730] = 0, 2
    assert battle_restrictions(mem, 'wild', True) == (False, False)
    mem[0xC730], mem[0xD230] = 0, 9
    assert battle_restrictions(mem, 'wild', True) == (False, True)
    assert battle_restrictions(mem, 'wild', False) == (None, None)


def test_failed_escape_replans_from_fresh_health():
    s = state((mon(), mon(slot=2, level=5)), mon(level=12))
    own = NS(battle_strategy=Gold97BattleStrategy(), battle_target=None,
             _set_provider_event=lambda text: None, pause=lambda text: pytest.fail(text))
    executor = BattleExecutor()
    s.battle_menu_cursor = (2, 2)
    assert executor.step(own, s) == 'a'
    assert executor.action.kind == 'escape'
    s.battle_menu_kind = 'text'
    s.screen_lines = ("Can't escape!",)
    s.battle = replace(s.battle, active=replace(s.party[0], hp=25))
    executor.step(own, s)
    s.battle_menu_kind = 'command'
    s.screen_lines = ()
    assert executor.step(own, s) == 'a'
    assert executor.action.kind == 'escape'


def test_required_opponent_and_healing_completion_retain_goal(tmp_path):
    controller = Gold97Controller('resume', database=tmp_path / 'proof.sqlite', vision_enabled=False)
    try:
        s = state((mon(hp=20), mon(level=5)))
        controller.training.data.setdefault('opponents', {})[s.area_name] = asdict(mon(level=12))
        goal = controller.route.now
        controller._service_route = lambda *args, **kw: 'left'
        assert controller._recovery_action(s, overworld=True) == 'left'
        s.area_name, s.map_group, s.map_number = 'Pagota Pokemon Center', 10, 14
        s.party = (mon(), mon(level=5))
        controller._recovery_action(s, overworld=True)
        assert controller.recovery['exit']
        s.area_name, s.map_group, s.map_number = 'Brass Tower', 3, 2
        assert controller._recovery_action(s, overworld=True) is None
        assert controller.recovery is None
        assert controller.route.now == goal
    finally:
        controller.close()
