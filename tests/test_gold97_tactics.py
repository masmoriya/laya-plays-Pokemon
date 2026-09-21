from dataclasses import replace
from types import SimpleNamespace as NS

from jpp.decode import Mon, Battle
from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle_executor import BattleExecutor
from jpp.agent.gold97_battle_menus import party_step
from jpp.agent.gold97_damage import estimate
from jpp.agent.gold97_mechanics import compatible, multiplier, REFERENCE
from jpp.agent.gold97_screen import battle_menu
from jpp.agent.gold97_services import needs_healing, fully_recovered


def mon(slot=1, **kwargs):
    values = dict(slot=slot, species='VOLBEAR', species_id=156, level=20,
                  hp=60, max_hp=60, status='none', types=('FIRE',),
                  moves=('LEER', 'EMBER', 'BITE'), pp=(30, 25, 25),
                  stats=(45, 40, 40, 45, 40), stages=(0,) * 7)
    values.update(kwargs)
    return Mon(**values)


def state(active=None, foe=None, **kwargs):
    active = active or mon()
    foe = foe or mon(0, species='PIDGEY', species_id=16, types=('NORMAL',),
                     moves=('TACKLE',), pp=(30,))
    values = dict(battle=Battle('trainer', active, foe), party=(active,),
                  active_slot=0, battle_menu_kind='command', battle_menu_cursor=(1, 1),
                  screen_lines=(), screen_cursor=None, potion_count=0)
    values.update(kwargs)
    return NS(**values)


def owner():
    value = NS(battle_strategy=Gold97BattleStrategy(), battle_switch_phase=None,
               battle_target=None, paused=False, message='')
    value._set_provider_event = lambda text: setattr(value, 'message', text)
    value.pause = lambda text: (setattr(value, 'paused', True), setattr(value, 'message', text))
    return value


def test_attack_finishes_without_leer_and_is_repeatable():
    st = state(foe=mon(0, hp=1))
    planner = Gold97BattleStrategy()
    decisions = [planner.plan(st) for _ in range(4)]
    assert len(set(decisions)) == 1
    assert decisions[0].kind == 'move' and decisions[0].target != 0


def test_dark_is_physical_and_ghost_is_special():
    attacker = mon(stats=(100, 40, 40, 10, 40))
    foe = mon(types=('NORMAL',), stats=(40, 40, 40, 40, 40))
    assert estimate(attacker, foe, 'BITE').high > estimate(attacker, foe, 'EMBER').high
    ghost_target = replace(foe, types=('PSYCHIC',))
    assert estimate(attacker, ghost_target, 'SHADOW BALL').high < estimate(
        replace(attacker, stats=(10, 40, 40, 100, 40)), ghost_target, 'SHADOW BALL').high


def test_fixed_damage_immunity_and_false_swipe():
    attacker, foe = mon(), mon(0, hp=10)
    assert estimate(attacker, foe, 'DRAGON RAGE').low == 40
    assert estimate(attacker, foe, 'SEISMIC TOSS').low == 20
    assert estimate(attacker, replace(foe, types=('GHOST',)), 'TACKLE').high == 0
    assert estimate(attacker, foe, 'FALSE SWIPE').high <= 9
    assert estimate(attacker, replace(foe, level=30), 'GUILLOTINE').accuracy == 0


def test_setup_requires_shorter_complete_sequence():
    active = mon(hp=999, max_hp=999, moves=('SCREECH', 'TACKLE'), pp=(20, 30),
                 stats=(30, 999, 40, 30, 999), types=('NORMAL',))
    foe = mon(0, hp=100, max_hp=100, stats=(1, 80, 10, 1, 80), types=('NORMAL',),
              moves=('TACKLE',), pp=(30,))
    planner = Gold97BattleStrategy()
    assert planner.attack(active, foe).target == 0
    # Merely planning does not mark setup used; the observed stage does.
    assert planner.attack(active, foe).target == 0
    assert planner.attack(active, replace(foe, stages=(0, -6, 0, 0, 0, 0, 0))).target == 1


def test_forced_switch_uses_identity_not_species():
    first, second = mon(1, hp=0), mon(2)
    st = state(first, party=(first, second))
    assert Gold97BattleStrategy().plan(st, forced=True).target == 1


def test_optional_switch_stays_without_verified_next_opponent():
    assert Gold97BattleStrategy().plan(state(), optional=True).kind == 'stay'


def test_optional_switch_chooses_safer_bench():
    active = mon(hp=1)
    bench = mon(2, hp=100, max_hp=100, stats=(100, 150, 100, 100, 150))
    st = state(active, party=(active, bench))
    st.upcoming_opponent = st.battle.opponent
    action = Gold97BattleStrategy().plan(st, optional=True)
    assert action.kind == 'switch' and action.target == 1


def test_regular_switch_survives_entry_hit_and_following_turn():
    active = mon(hp=1)
    bench = mon(2, hp=100, max_hp=100, stats=(100, 150, 100, 100, 150))
    st = state(active, party=(active, bench))
    assert Gold97BattleStrategy().plan(st).kind == 'switch'
    st.party = (active, replace(bench, hp=1))
    assert Gold97BattleStrategy().plan(st).kind == 'move'


def test_potion_only_when_it_buys_survival():
    st = state(mon(hp=1), foe=mon(0, stats=(5, 40, 60, 5, 40), moves=('TACKLE',), pp=(30,)),
               potion_count=1)
    assert Gold97BattleStrategy().plan(st).kind == 'heal'
    st.potion_count = 0
    assert Gold97BattleStrategy().plan(st).kind != 'heal'


def test_switch_prompt_selects_no_and_does_not_reconfirm_same_frame():
    ex, own = BattleExecutor(), owner()
    st = state(battle_menu_kind='switch_prompt', screen_lines=('Will you change', 'YES', 'NO'),
               screen_cursor=(1, 1))
    assert ex.step(own, st) == 'down'
    st.screen_cursor = (1, 2)
    assert ex.step(own, st) == 'a'
    assert ex.step(own, st) is None


def test_already_out_recovers_then_cancels_party():
    ex, own = BattleExecutor(), owner()
    st = state(battle_menu_kind='party', screen_lines=('VOLBEAR is already out.',))
    assert ex.step(own, st) == 'a'
    assert ex.step(own, st) is None
    st.screen_lines = ('Choose a Pokemon',)
    assert ex.step(own, st) == 'b'


def test_optional_switch_never_confirms_the_active_slot():
    from jpp.agent.gold97_battle import BattleAction
    ex, own = BattleExecutor(), owner()
    ex.action = BattleAction('switch', 0, 'Switch')
    ex.phase = 'optional_switch'
    st = state(battle_menu_kind='party', battle_menu_cursor=(1, 1))
    assert ex.step(own, st) == 'b'
    assert ex.decline_optional_switch
    st.battle_menu_kind = 'switch_prompt'
    st.screen_lines = ('Will you change', 'YES', 'NO')
    st.screen_cursor = (1, 1)
    assert ex.step(own, st) == 'down'
    st.screen_cursor = (1, 2)
    assert ex.step(own, st) == 'a'
    assert ex.action.kind == 'stay'


def test_already_out_rejection_declines_the_same_optional_offer():
    from jpp.agent.gold97_battle import BattleAction
    ex, own = BattleExecutor(), owner()
    ex.action = BattleAction('switch', 0, 'Switch')
    ex.phase = 'optional_switch'
    st = state(battle_menu_kind='party', screen_lines=('VOLBEAR is already out.',))
    assert ex.step(own, st) == 'a'
    st.screen_lines = ('Choose a Pokemon',)
    assert ex.step(own, st) == 'b'
    st.battle_menu_kind = 'switch_prompt'
    st.screen_lines = ('Will you change', 'YES', 'NO')
    st.screen_cursor = (1, 1)
    assert ex.step(own, st) == 'down'
    assert ex.action.kind == 'stay'


def test_rejected_switch_target_stays_blocked_until_active_slot_changes():
    from jpp.agent.gold97_battle import BattleAction
    ex, own = BattleExecutor(), owner()
    ex.action = BattleAction('switch', 0, 'Switch')
    ex.phase = 'switch'
    st = state(battle_menu_kind='party', screen_lines=('VOLBEAR is already out.',),
               active_slot=1)
    assert ex.step(own, st) == 'a'
    st.screen_lines = ('Choose a Pokemon',)
    assert ex.step(own, st) == 'b'
    ex.action = BattleAction('switch', 0, 'Switch')
    assert ex.step(own, st) == 'b'
    st.active_slot = 2
    ex.action = BattleAction('switch', 0, 'Switch')
    assert ex.step(own, st) == 'a'


def test_party_navigation_is_one_vertical_list():
    assert party_step((1, 1), 3) == 'down'
    assert party_step((1, 4), 3) == 'a'
    assert party_step((1, 5), 1) == 'up'


def test_original_move_slot_and_stale_confirmation():
    ex, own = BattleExecutor(), owner()
    st = state(mon(moves=('EMBER',), pp=(25,), move_slots=(2,)),
               battle_menu_kind='moves', battle_menu_cursor=(1, 1))
    assert ex.step(own, st) == 'down'
    st.battle_menu_cursor = (1, 3)
    assert ex.step(own, st) == 'a'
    assert ex.step(own, st) is None
    st.battle = replace(st.battle, active=replace(st.battle.active, pp=(24,)))
    st.battle_menu_kind = 'text'
    assert ex.step(own, st) == 'a'


def test_missing_battle_state_waits_then_pauses():
    ex, own = BattleExecutor(), owner()
    st = state(); st.battle = Battle('trainer', None, None)
    st.party, st.active_slot = (), None
    for _ in range(50):
        assert ex.step(own, st) is None
    assert own.paused


def test_trainer_intro_advances_before_active_pokemon_is_loaded():
    ex, own = BattleExecutor(), owner()
    st = state(battle_menu_kind='text', screen_lines=('FLEDGLING JOHNNY sent out CHIX.',))
    st.battle = Battle('trainer', None, None)
    st.party, st.active_slot = (), None
    assert ex.step(own, st) == 'a'
    assert not own.paused


def test_party_switch_submenu_is_not_confused_with_party_selection():
    lines = [''] * 18
    lines[1], lines[2], lines[7] = 'VOLBEAR', '19', 'CANCEL'
    lines[10], lines[12], lines[14] = 'SWITCH', 'STATS', 'CANCEL'
    tiles = [[0] * 20 for _ in range(18)]
    tiles[1][0] = tiles[10][12] = 0xED
    assert battle_menu(lines, tiles) == ('party_action', (12, 10))


def test_screen_reads_lower_vertical_party_slots_and_dynamic_cancel():
    lines = [''] * 18
    for row, name in zip((1, 3, 5, 7, 9), ('ONE', 'TWO', 'THREE', 'FOUR', 'FIVE')):
        lines[row], lines[row + 1] = name, '20 20'
    lines[11] = 'CANCEL'
    tiles = [[0] * 20 for _ in range(18)]
    tiles[7][0] = 0xED
    assert battle_menu(lines, tiles) == ('party', (1, 4))
    tiles[7][0], tiles[11][0] = 0, 0xED
    assert battle_menu(lines, tiles) == ('party', (1, 0))


def test_screen_recognizes_optional_offer_before_generic_text():
    lines = [''] * 18
    lines[12], lines[14], lines[16], lines[17] = 'Will LAYA', 'change POK MON?', 'YES', 'NO'
    assert battle_menu(lines, [[0] * 20 for _ in range(18)])[0] == 'switch_prompt'


def test_readiness_includes_status_and_exhausted_attacks():
    st = state(mon(status='poison'))
    assert needs_healing(st)
    st.party = (mon(pp=(30, 0, 0)),)
    assert needs_healing(st)
    st.party = (mon(max_pp=(30, 25, 25), pp=(30, 24, 25)),)
    assert not fully_recovered(st)
    st.party = (mon(max_pp=(30, 25, 25)),)
    assert fully_recovered(st)


def test_mechanics_reject_unrelated_or_truncated_rom():
    assert not compatible(b'not a cartridge')
    assert REFERENCE['revision'] == '976507f9e6e605050384e9ec12e9651988ae7c46'


def test_already_out_recovers_even_when_battle_struct_is_temporarily_unreadable():
    ex, own = BattleExecutor(), owner()
    st = state(battle_menu_kind='party', screen_lines=('VOLBEAR is already out.',))
    st.battle = Battle('trainer', None, st.battle.opponent)
    assert ex.step(own, st) == 'a'
    st.screen_lines = ('Choose a Pokemon',)
    assert ex.step(own, st) == 'b'


def test_healing_waits_for_inventory_consumption_before_replanning():
    from jpp.agent.gold97_battle import BattleAction
    ex, own = BattleExecutor(), owner()
    ex.action = BattleAction('heal', 0, 'Heal')
    ex.phase = 'heal'
    st = state(mon(hp=1), potion_count=1, battle_menu_kind='text',
               screen_lines=('POTION', 'CANCEL'), screen_cursor=(0, 0))
    assert ex.step(own, st) == 'a'
    st.screen_lines = ('POTION', 'USE', 'CANCEL'); st.screen_cursor = (0, 1)
    assert ex.step(own, st) == 'a'
    st.battle_menu_kind = 'party'; st.battle_menu_cursor = (1, 1)
    assert ex.step(own, st) == 'a'
    st.battle = replace(st.battle, active=replace(st.battle.active, hp=21))
    assert ex.step(own, st) is None
    assert ex.action.kind == 'heal'
    st.potion_count = 0; st.battle_menu_kind = 'command'
    assert ex.step(own, st) == 'a'
    assert ex.action.kind == 'move'


def test_incompatible_cartridge_does_not_execute_assumed_mechanics():
    ex, own = BattleExecutor(), owner()
    st = state(mechanics_verified=False)
    assert ex.step(own, st) is None
    assert own.paused


def test_newly_visible_menu_retries_an_ignored_press_after_waiting():
    ex, own = BattleExecutor(), owner()
    st = state()
    assert ex.step(own, st) == 'a'
    for _ in range(5):
        assert ex.step(own, st) is None
    assert ex.step(own, st) == 'a'


def test_rejected_actions_cannot_loop_across_alternating_menus():
    ex, own = BattleExecutor(), owner()
    st = state()
    for _ in range(12):
        st.battle_menu_kind = 'command'; st.battle_menu_cursor = (1, 1)
        ex.step(own, st)
        if own.paused:
            break
        st.battle_menu_kind = 'moves'
        st.battle_menu_cursor = (1, (ex.action.target + 1) if ex.action else 2)
        ex.step(own, st)
        st.battle_menu_kind = 'text'; st.screen_lines = ('Move was rejected',)
        ex.step(own, st)
    assert own.paused


def test_forced_party_confirmation_retries_when_first_tap_is_ignored():
    executor, control = BattleExecutor(), owner()
    st = state(mon(hp=0), party=(mon(hp=0), mon(2)),
               battle_menu_kind='party', battle_menu_cursor=(1, 2))
    assert executor.step(control, st) == 'a'
    for _ in range(5):
        assert executor.step(control, st) is None
    assert executor.step(control, st) == 'a'
    assert not control.paused
