from types import SimpleNamespace

from jpp.agent.gold97_journey_nav import journey_step
from jpp.route_progress import RouteProgress


class Memory:
    def __init__(self):
        self.world = {}

    def map(self, key):
        return {"visited": [], "blocked": [], "edges": []}

    def save(self):
        pass


def _state(group, number, x, y, width=52, height=38):
    return SimpleNamespace(map_group=group, map_number=number, x=x, y=y,
                           map_width=width, map_height=height, in_battle=False)


def test_pagota_leg_uses_verified_cave_passage_and_gate():
    route = RouteProgress(completed={1, 2})
    memory = Memory()
    assert journey_step(_state(20, 2, 43, 31), memory, route,
                        overworld=True)[1] in {"up", "left"}
    assert journey_step(_state(3, 50, 49, 30, 50, 36), memory, route,
                        overworld=True)[1] == "left"
    assert journey_step(_state(3, 50, 42, 30, 50, 36), memory, route,
                        overworld=True)[1] == "up"
    assert journey_step(_state(20, 2, 8, 27), memory, route,
                        overworld=True)[1] == "up"
    assert journey_step(_state(20, 10, 4, 7, 10, 8), memory, route,
                        overworld=True)[1] == "up"


def test_brass_tower_leg_targets_each_stair_warp():
    route = RouteProgress(completed={1, 2, 3})
    memory = Memory()
    positions = ((9, 2, 16, 22, 40, 36), (3, 1, 5, 10, 12, 12),
                 (3, 2, 1, 1, 12, 12), (3, 3, 11, 4, 12, 12),
                 (3, 4, 10, 1, 12, 12), (3, 5, 5, 5, 6, 6))
    for group, number, x, y, width, height in positions:
        result = journey_step(_state(group, number, x, y, width, height),
                              memory, route, overworld=True)
        assert result and result[0] == "Climb Brass Tower"
        assert result[1] in {"up", "down", "left", "right"}


def test_brass_tower_visits_kurt_before_tower():
    route = RouteProgress(completed={1, 2, 3})
    memory = Memory()
    city = _state(9, 2, 16, 22, 40, 36)
    assert journey_step(city, memory, route, overworld=True)[1] in {
        "left", "down"
    }
    house = _state(9, 12, 3, 6, 16, 8)
    assert journey_step(house, memory, route, overworld=True)[1] == "down"
    assert journey_step(_state(9, 12, 3, 7, 16, 8), memory, route,
                        overworld=True) == ("Leave Kurt's house", "down")
    city.talked_to_kurt_and_falkner = True
    assert journey_step(city, memory, route, overworld=True)[1] in {
        "left", "up"
    }
