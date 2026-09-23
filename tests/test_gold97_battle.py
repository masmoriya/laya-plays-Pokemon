from types import SimpleNamespace

from jpp.agent.gold97_battle import Gold97BattleStrategy
from jpp.agent.gold97_battle import BattleAction
from jpp.agent.gold97_battle_executor import BattleExecutor


def mon(moves, pp, species="FLAMBEAR", types=()):
    return SimpleNamespace(species=species, species_id=155, moves=tuple(moves),
                           pp=tuple(pp), types=tuple(types))


def test_strategy_skips_exhausted_first_move():
    strategy = Gold97BattleStrategy()
    assert strategy.choose(mon(("TACKLE", "EMBER"), (0, 5))) == 1


def test_strategy_repeats_best_available_attack():
    strategy = Gold97BattleStrategy()
    active = mon(("TACKLE", "EMBER"), (5, 5))
    assert strategy.choose(active) == 1
    assert strategy.choose(active) == 1
    assert strategy.choose(active) == 1


def test_strategy_uses_status_move_only_when_no_attack_remains():
    strategy = Gold97BattleStrategy()
    assert strategy.choose(mon(("GROWL", "TACKLE"), (5, 5))) == 1
    assert strategy.choose(mon(("GROWL",), (5,))) == 0


def test_strategy_returns_none_when_every_move_is_empty():
    assert Gold97BattleStrategy().choose(mon(("TACKLE", "GROWL"), (0, 0))) is None


def test_strategy_treats_cartridge_ohko_as_an_attack():
    foe = SimpleNamespace(types=("NORMAL",))
    assert Gold97BattleStrategy().choose(
        mon(("GUILLOTINE", "LEER"), (5, 5)), foe) == 0


def test_strategy_handles_unknown_move_names_without_crashing():
    assert Gold97BattleStrategy().choose(mon(("UNKNOWN MOVE",), (5,))) == 0


def test_strategy_prefers_effective_attack_over_neutral_attack():
    strategy = Gold97BattleStrategy()
    active = mon(("TACKLE", "EMBER"), (5, 5))
    foe = SimpleNamespace(types=("GRASS",))
    assert strategy.choose(active, foe) == 1


def test_strategy_uses_generation_two_type_matchups():
    foe = SimpleNamespace(types=("GRASS", "BUG"))
    assert Gold97BattleStrategy().choose(mon(("TACKLE", "EMBER"), (5, 5)), foe) == 1

    foe = SimpleNamespace(types=("GHOST",))
    assert Gold97BattleStrategy().choose(mon(("TACKLE", "BITE"), (5, 5)), foe) == 1

    foe = SimpleNamespace(types=("ICE",))
    assert Gold97BattleStrategy().choose(mon(("TACKLE", "STEEL WING"), (5, 5)), foe) == 1


def test_strategy_avoids_normal_into_ghost_when_an_attack_is_available():
    foe = SimpleNamespace(types=("GHOST",))
    active = mon(("TACKLE", "EMBER"), (5, 5))
    assert Gold97BattleStrategy().choose(active, foe) == 1


def test_strategy_prefers_water_and_electric_matchups():
    assert Gold97BattleStrategy().choose(
        mon(("TACKLE", "WATER GUN"), (5, 5)), SimpleNamespace(types=("FIRE",))) == 1
    assert Gold97BattleStrategy().choose(
        mon(("TACKLE", "THUNDERSHOCK"), (5, 5)),
        SimpleNamespace(types=("WATER",))) == 1


def test_strategy_does_not_assume_leer_is_worth_a_turn():
    active = mon(("LEER", "TACKLE"), (5, 5))
    active.hp, active.max_hp = 30, 30
    foe = SimpleNamespace(species="PIDGEY", species_id=16, types=("NORMAL",),
                           hp=20, max_hp=20)
    strategy = Gold97BattleStrategy()
    assert strategy.choose(active, foe) == 1
    assert strategy.choose(active, foe) == 1


def test_strategy_does_not_waste_critical_turn_on_unproven_sand_attack():
    active = mon(("SAND ATTACK", "TACKLE"), (5, 5))
    active.hp, active.max_hp = 3, 10
    foe = SimpleNamespace(species="PIDGEY", species_id=16, types=("NORMAL",),
                           hp=20, max_hp=20)
    strategy = Gold97BattleStrategy()
    assert strategy.choose(active, foe) == 1
    assert strategy.choose(active, foe) == 1


def test_strategy_attacks_a_nearly_fainted_foe_instead_of_setting_up():
    active = mon(("SAND ATTACK", "TACKLE"), (5, 5))
    active.hp, active.max_hp = 3, 10
    foe = SimpleNamespace(species="PIDGEY", species_id=16, types=("NORMAL",),
                           hp=2, max_hp=20)
    assert Gold97BattleStrategy().choose(active, foe) == 1


def test_strategy_does_not_delay_a_super_effective_attack_for_setup():
    active = mon(("LEER", "EMBER"), (5, 5))
    active.hp, active.max_hp = 30, 30
    foe = SimpleNamespace(species="CATERPIE", species_id=123, types=("GRASS",),
                           hp=20, max_hp=20)
    assert Gold97BattleStrategy().choose(active, foe) == 1


def test_stalled_potion_menu_is_cancelled_and_not_reopened_for_same_battle_state():
    active = mon(("TACKLE",), (5,))
    active.hp, active.max_hp = 3, 22
    foe = SimpleNamespace(species="PINSIR", species_id=127, types=("BUG",),
                          hp=57, max_hp=59)
    state = SimpleNamespace(mechanics_verified=True, active_slot=0,
        battle=SimpleNamespace(kind="trainer", active=active, opponent=foe),
        battle_menu_kind="text", battle_menu_cursor=None,
        screen_cursor=(14, 8), screen_lines=("POTION", "", "X ACC USE", "ESC QUIT"),
        potion_count=4, poke_ball_count=1)

    class Planner:
        def __init__(self):
            self.events = []

        def reset(self):
            pass

        def plan(self, state, **kwargs):
            return BattleAction("heal", 0, "Heal: survive retaliation")

        def attack(self, active, opponent):
            return BattleAction("move", 0, "Attack after stalled healing")

    owner = SimpleNamespace(battle_strategy=Planner(), battle_switch_phase=None,
                            _set_provider_event=lambda message: None)
    executor = BattleExecutor()
    executor.action = BattleAction("heal", 0, "Heal: survive retaliation")
    executor.phase = "heal"

    for _ in range(47):
        action = executor.step(owner, state)
    assert action == "b"
    assert executor.failed_heal_signature == executor.signature(state)

    state.battle_menu_kind = "command"
    state.battle_menu_cursor = (0, 0)
    state.screen_cursor = None
    state.screen_lines = ()
    executor.step(owner, state)
    assert executor.action.kind == "move"
    assert executor.failed_heal_signature is None
