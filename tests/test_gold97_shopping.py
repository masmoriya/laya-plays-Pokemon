from types import SimpleNamespace

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_shopping import mart_menu_step


def _screen(*lines, cursor=(1, 2)):
    return SimpleNamespace(screen_lines=lines, screen_cursor=cursor)


def test_mart_selects_buy_and_only_the_ball_row():
    plan = {"selected_ball": False}
    assert mart_menu_step(plan, _screen("BUY", "SELL", "QUIT", cursor=(1, 4))) == (
        "up", "choose_buy")
    assert mart_menu_step(plan, _screen("BUY", "SELL", "QUIT")) == ("a", "choose_buy")
    assert mart_menu_step(plan, _screen("", "", "", "", "POK  BALL", "", "POTION",
                                        cursor=(1, 6))) == ("up", "choose_ball")
    assert not plan["selected_ball"]
    assert mart_menu_step(plan, _screen("", "", "", "", "POK  BALL", "", "POTION",
                                        cursor=(1, 4))) == ("a", "choose_ball")
    assert plan["selected_ball"]
    assert mart_menu_step(plan, _screen("HOW MANY?")) == ("a", "quantity")
    assert mart_menu_step(plan, _screen("POK  BALL", "POTION", "HOW MANY?",
                                        cursor=None)) == ("a", "quantity")
    assert mart_menu_step(plan, _screen("1 POK  BALL will be 200!")) == (
        "a", "confirm")


def test_mart_does_not_confirm_unknown_item_or_quantity():
    plan = {"selected_ball": False}
    assert mart_menu_step(plan, _screen("POTION", "ESCAPE ROPE", "CANCEL")) is None
    assert mart_menu_step(plan, _screen("HOW MANY?")) is None


def test_mart_entrance_waits_for_menu_instead_of_confirming_unknown_item(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        controller.shopping = {"target": (3, 26), "town": ((9, 2), 1000, 0),
                               "last_balls": 0, "selected_ball": False,
                               "last_ui": None, "repeats": 0, "talks": 0}
        state = SimpleNamespace(map_group=9, map_number=3, area_name="Pagota Mart",
                                in_battle=False, party=(SimpleNamespace(hp=20, max_hp=20),),
                                x=4, y=7, poke_ball_count=0, money=1000,
                                screen_lines=(), screen_cursor=None)
        assert controller._shopping_action(state, overworld=False) == "wait"
        state.screen_lines = ("POTION", "ESCAPE ROPE", "CANCEL")
        state.screen_cursor = (1, 2)
        assert controller._shopping_action(state, overworld=False) == "b"
        assert controller.shopping["exit"]
    finally:
        controller.close()
