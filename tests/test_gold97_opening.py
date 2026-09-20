"""Opening goals are tied to cartridge progress, not action frequency."""

from types import SimpleNamespace

from jpp.agent.gold97_opening import Gold97Opening, _route


class Memory:
    def __init__(self, blocked=()):
        self.area = {"blocked": list(blocked), "visited": []}

    def map(self, _key):
        return self.area


def state(number, x, y, *, email=False, scene=0, party=(), battle="none"):
    return SimpleNamespace(
        map_group=20, map_number=number, x=x, y=y,
        map_width=20, map_height=24, read_oaks_email=email,
        opening_scene=scene, party=party, in_battle=battle != "none",
        battle=SimpleNamespace(kind=battle),
    )


def test_planner_replans_around_a_confirmed_wall():
    area = {"blocked": [[[1, 1], "left"]], "visited": []}
    assert _route(area, (1, 1), (0, 1), 3, 3) != "left"


def test_email_is_a_required_goal_before_the_upstairs_exit():
    planner = Gold97Opening()
    memory = Memory()
    assert planner.choose(state(7, 3, 2), memory, overworld=True) == (
        "Read Oak's email on the PC", "up"
    )
    assert planner.choose(state(7, 3, 2), memory, overworld=True) == (
        "Read Oak's email on the PC", "a"
    )
    assert planner.choose(state(7, 9, 0, email=True), memory, overworld=True) == (
        "Go downstairs after reading Oak's email", "up"
    )


def test_bedroom_route_uses_the_verified_corridor_from_either_save():
    planner = Gold97Opening()
    memory = Memory()
    assert planner.choose(state(7, 6, 2), memory, overworld=True)[1] == "down"
    assert planner.choose(state(7, 9, 2), memory, overworld=True)[1] == "down"


def test_scene_flags_gate_the_scripted_lab_and_supplies():
    planner = Gold97Opening()
    memory = Memory()
    assert planner.choose(state(5, 3, 5, scene=0), memory, overworld=True)[1] == "wait"
    assert planner.choose(state(5, 5, 3, scene=1), memory, overworld=True)[1] == "up"
    flambear = (SimpleNamespace(species="FLAMBEAR"),)
    assert planner.choose(state(5, 5, 3, scene=1, party=flambear),
                          memory, overworld=False)[1] == "b"
    assert planner.choose(state(4, 4, 2, scene=3, party=flambear,
                                battle="trainer"), memory, overworld=False)[1] == "a"
    assert planner.choose(state(4, 4, 11, scene=4, party=flambear),
                          memory, overworld=True)[1] == "wait"
    assert planner.choose(state(4, 4, 15, scene=2, party=flambear),
                          memory, overworld=True)[1] == "down"


def test_route101_goal_does_not_reenter_the_lab_door():
    planner = Gold97Opening()
    memory = Memory()
    flambear = (SimpleNamespace(species="FLAMBEAR"),)
    assert planner.choose(state(3, 15, 19, scene=2, party=flambear),
                          memory, overworld=True) == ("Reach Route 101", "down")
    assert planner.choose(state(3, 15, 20, scene=2, party=flambear),
                          memory, overworld=True)[1] != "up"
