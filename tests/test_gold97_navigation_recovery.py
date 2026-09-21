"""Regression coverage for drift, repeated successful moves and gym exits."""

from types import SimpleNamespace

from jpp.agent.gold97_journey_nav import journey_step
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_navigation import MovementHistory, STEPS
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


def test_drift_does_not_create_a_false_edge(tmp_path):
    memory = Gold97Memory('run', tmp_path / 'memory.sqlite')
    try:
        memory.move_result('09:04', (4, 5), 'right', (3, 5))
        memory.move_result('09:04', (3, 5), 'up', (3, 3))
        assert not memory.map('09:04')['edges']
        memory.move_result('09:04', (3, 3), 'down', (3, 4))
        assert memory.map('09:04')['edges'] == [[[3, 3], 'down']]
    finally:
        memory.close()


def test_old_corrupt_edges_are_removed_without_losing_facts(tmp_path):
    path = tmp_path / 'memory.sqlite'
    memory = Gold97Memory('run', path)
    memory.world['navigation_version'] = 2
    memory.map('09:04')['edges'] = [[[4, 5], 'right']]
    memory.remember('clue', 'Earned badge')
    memory.close()
    memory = Gold97Memory('run', path)
    try:
        assert memory.map('09:04')['edges'] == []
        assert memory.relevant('09:04')[0]['value'] == 'Earned badge'
    finally:
        memory.close()


def test_successful_circle_chooses_unvisited_road_and_idle_is_not_a_loop():
    history = MovementHistory()
    for _ in range(30):
        history.observe('09:04', (3, 3))
    assert not history.looping
    for point in [(4, 3), (4, 4), (3, 4), (3, 3)] * 2:
        history.observe('09:04', point)
    assert history.looping
    assert history.choose('09:04', (3, 3), {'right': '', 'left': ''}) == 'left'
    history.observe('09:02', (3, 3))
    assert not history.looping


def test_badge_exit_replans_through_winding_road(tmp_path):
    # A synthetic collision fixture checks the algorithm, not cartridge layout.
    width, height = 10, 16
    road = {(3, 3), (4, 3), (5, 3)} | {(5, y) for y in range(3, 10)}
    road |= {(x, 9) for x in range(2, 6)} | {(2, y) for y in range(9, 16)}
    tiles = bytes(0 if (x, y) in road else 7
                  for y in range(height) for x in range(width))
    terrain = Gold97CollisionMap((9, 4), width, height, tiles)
    state = SimpleNamespace(map_group=9, map_number=4, x=3, y=3,
                            map_width=width, map_height=height,
                            in_battle=False, badge_ids=(1,))
    memory = Gold97Memory('run', tmp_path / 'memory.sqlite')
    try:
        route = RouteProgress(completed={1, 2, 3, 4, 5})
        positions = []
        for _ in range(30):
            result = journey_step(state, memory, route, overworld=True, terrain=terrain)
            assert result and result[0] == 'Leave Pagota Gym after Falkner'
            if (state.x, state.y) == (2, 15):
                assert result[1] == 'down'
                break
            origin = (state.x, state.y)
            assert origin not in positions
            positions.append(origin)
            dx, dy = STEPS[result[1]]
            state.x += dx
            state.y += dy
            assert (state.x, state.y) in road
            memory.move_result('09:04', origin, result[1], (state.x, state.y))
        assert (state.x, state.y) == (2, 15)
        state.badge_ids = ()
        assert journey_step(state, memory, route, overworld=True, terrain=terrain) is None
    finally:
        memory.close()


def test_native_movement_hold_is_quiet_until_controller_releases_it():
    from jpp.agent.gold97_input import renew_movement

    class Emulator:
        def __init__(self):
            self.events = []

        def button_release(self, action):
            self.events.append(('release', action))

    emulator = Emulator()
    active = renew_movement(emulator, 'right', 'right',
                            overworld=True, in_battle=False)
    assert active == 'right'
    assert emulator.events == []
    active = renew_movement(emulator, active, 'right',
                            overworld=True, in_battle=False)
    assert active == 'right'
    # A changed or cleared controller intent releases the physical button.
    active = renew_movement(emulator, active, None,
                            overworld=True, in_battle=False)
    assert active is None
    assert emulator.events == [('release', 'right')]
