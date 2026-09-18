from jpp import route, symbols as S
from jpp.decode import decode
from jpp.goals import GOALS

import make_ram

BLOCKED, FREE = 1, route.WALKABLE


def grid(*free_directions):
    """A 20x18 collision grid where only the named neighbours are walkable."""
    g = [[BLOCKED] * 20 for _ in range(18)]
    for d in free_directions:
        dx, dy = route._DELTA[d]
        g[route.PLAYER_ROW + dy * route.STEP_TILES][route.PLAYER_COL + dx * route.STEP_TILES] = FREE
    return g


def state_at(map_id, x, y):
    ram = make_ram.overworld()
    ram[S.CUR_MAP] = map_id
    ram[S.X_COORD], ram[S.Y_COORD] = x, y
    return decode(bytes(ram))


def goal(name):
    return next(g for g in GOALS if g.name == name)


def test_every_goal_with_walking_has_a_waypoint_on_every_map_it_crosses():
    assert route.WAYPOINTS["leave_house"][S.REDS_HOUSE_2F] == (7, 1)  # RedsHouse2F.asm warp
    assert route.WAYPOINTS["leave_house"][S.REDS_HOUSE_1F] == (2, 7)  # RedsHouse1F.asm warp
    assert route.WAYPOINTS["get_starter"][S.PALLET_TOWN] == (12, 11)  # PalletTown.asm warp
    assert route.WAYPOINTS["win_lab_rival"] == {}  # the battle happens where we stand
    assert set(route.WAYPOINTS) == {g.name for g in GOALS}


def test_waypoint_for_returns_none_off_route():
    st = state_at(S.VIRIDIAN_CITY, 1, 1)
    assert route.waypoint_for(goal("get_starter"), st) is None


def test_stepping_closes_x_then_y():
    waypoint = (12, 11)
    assert route.next_step(state_at(S.PALLET_TOWN, 10, 8), waypoint) == "right"
    assert route.next_step(state_at(S.PALLET_TOWN, 14, 8), waypoint) == "left"
    assert route.next_step(state_at(S.PALLET_TOWN, 12, 8), waypoint) == "down"
    assert route.next_step(state_at(S.PALLET_TOWN, 12, 14), waypoint) == "up"
    assert route.next_step(state_at(S.PALLET_TOWN, 12, 11), waypoint) is None


def test_one_free_sidestep_resolves_in_code():
    st = state_at(S.PALLET_TOWN, 10, 8)
    free = route.sidesteps(st, grid("right", "up"), (12, 11))
    assert free == ["right"]  # up does not shorten the walk, right does


def test_two_equally_good_sidesteps_are_the_tie_jev_breaks():
    st = state_at(S.PALLET_TOWN, 10, 8)
    free = route.sidesteps(st, grid("right", "down"), (12, 11))
    assert sorted(free) == ["down", "right"]  # both cut one tile off the distance


def test_a_dead_end_is_not_a_branch():
    st = state_at(S.PALLET_TOWN, 10, 8)
    assert route.sidesteps(st, grid("left", "up"), (12, 11)) == []
    assert route.sidesteps(st, grid(), (12, 11)) == []


def test_free_directions_reads_the_grid_and_stays_in_bounds():
    assert sorted(route.free_directions(grid("up", "left"))) == ["left", "up"]
    assert route.free_directions([[FREE] * 2] * 2) == []
