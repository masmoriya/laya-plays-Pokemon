from types import SimpleNamespace

from jpp.agent.gold97_learning import (
    learning_menu_step, proposed_move, replacement_index,
)


def mon(moves, types=("FIRE",)):
    return SimpleNamespace(species="FLAMBEAR", moves=moves, types=types)


def screen(moves, cursor_row=1, new_text=()):
    return SimpleNamespace(
        party=(mon(moves),), battle_menu_kind="text",
        screen_lines=tuple(new_text) + tuple(moves) + ("CANCEL",),
        screen_cursor=(1, cursor_row),
    )


def test_learn_dialogue_reads_the_named_move_across_lines():
    state = screen(("SCRATCH", "GROWL", "EMBER", "SAND ATTACK"),
                   new_text=("FLAMBEAR is trying", "to learn BITE!"))
    assert proposed_move(state) == "Bite"
    state.screen_lines = ("FLAMBEAR can't", "learn more than four moves")
    assert proposed_move(state) is None
    state.screen_lines = ("Can't learn more than four moves", "EMBER", "SCRATCH")
    assert proposed_move(state) is None


def test_bite_never_replaces_unique_fire_stab():
    current = mon(("EMBER", "SCRATCH", "SAND ATTACK", "GROWL"))
    assert replacement_index(current, "BITE") in (1, 2, 3)


def test_new_coverage_replaces_redundant_attack_over_existing_bite():
    current = mon(("SCRATCH", "BITE", "EMBER", "GROWL"))
    assert replacement_index(current, "WATER GUN") == 0


def test_move_menu_steers_from_cursor_and_confirms_only_the_chosen_row():
    moves = ("EMBER", "SCRATCH", "SAND ATTACK", "GROWL")
    state = screen(moves, cursor_row=0)
    target = replacement_index(state.party[0], "BITE")
    assert target is not None and target != 0
    action, detail = learning_menu_step(state, "BITE")
    assert action == "down" and "EMBER" not in detail
    state.screen_cursor = (1, target)
    assert learning_menu_step(state, "BITE")[0] == "a"


def test_unknown_move_or_cursor_never_confirms_a_deletion():
    state = screen(("EMBER", "SCRATCH", "SAND ATTACK", "GROWL"))
    assert learning_menu_step(state, None)[0] == "b"
    state.screen_cursor = None
    assert learning_menu_step(state, "BITE")[0] == "wait"
    state.screen_cursor = (1, 1)
    state.screen_lines = ("EMBER", "SCRATCH", "CANCEL")
    assert learning_menu_step(state, "BITE")[0] is None
    state.screen_lines = ("EMBER", "SCRATCH", "SAND ATTACK", "GROWL")
    assert learning_menu_step(state, None)[0] == "b"


def test_no_upgrade_navigates_to_cancel_without_losing_a_move():
    moves = ("EMBER", "SCRATCH", "BITE", "SAND ATTACK")
    state = screen(moves, cursor_row=0)
    assert replacement_index(state.party[0], "GROWL") is None
    assert learning_menu_step(state, "GROWL")[0] == "down"
    state.screen_cursor = (1, 4)
    assert learning_menu_step(state, "GROWL")[0] == "a"
    state.screen_lines = state.screen_lines[:-1]
    state.screen_cursor = (1, 0)
    assert learning_menu_step(state, "GROWL")[0] == "b"


def test_field_move_is_not_selected_for_deletion():
    current = mon(("CUT", "EMBER", "SCRATCH", "GROWL"))
    assert replacement_index(current, "BITE") != 0


def test_stop_learning_popup_ignores_hp_behind_no_row():
    lines = [' ' * 20 for _ in range(18)]
    lines[8] = ' ' * 16 + 'YES '
    lines[10] = '69' + ' ' * 14 + 'NO  '
    lines[14] = 'Stop learning'
    lines[16] = 'STUN SPORE?'
    state = screen(('TACKLE', 'ABSORB', 'SYNTHESIS', 'TAIL WHIP'))
    state.screen_lines, state.screen_cursor = tuple(lines), (15, 10)
    assert learning_menu_step(state, 'Stun Spore')[0] == 'up'
    state.screen_cursor = (15, 8)
    assert learning_menu_step(state, 'Stun Spore')[0] == 'a'
