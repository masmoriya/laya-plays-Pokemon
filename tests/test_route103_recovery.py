"""The Route 103 gate must not pin navigation to a failed remembered exit."""

from test_journey_strategy import controller, state

from jpp.agent.journey_targets import candidates, target_options
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


def route103(controller):
    s = state()
    s.map_group, s.map_number = 8, 4
    s.area_name = "Route 103"
    s.map_width, s.map_height = 20, 54
    s.x, s.y = 13, 49
    s.map_exits = ((12, 49, "", 9, 8), (13, 49, "", 9, 8),
                   (11, 0, "up", 8, 5))
    controller.route = RouteProgress(set(range(1, 11)))
    controller.memory.world["route"] = controller.route.to_dict()
    controller.strategy.observe(s, (), True)
    data = controller.strategy.data
    data["route_maps"]["11"] = ["09:08", "08:04"]
    data["connections"] = [
        {"from": "08:04", "at": [13, 49], "to": "09:08",
         "arrival": [5, 1], "direction": direction}
        for direction in ("down", "right")
    ]
    controller.memory.move_result("08:04", (13, 49), "right", (13, 49))
    terrain = Gold97CollisionMap((8, 4), 20, 54, bytes(1080))
    return s, terrain


def stale_exit():
    return {"id": "exit:08:04:09:08", "kind": "exit", "cell": [13, 49],
            "map": "08:04", "direction": "right", "destination_key": "09:08",
            "label": "Follow known exit to Route 103 Westport Gate",
            "completion": "Observe a map transition"}


def test_blocked_exit_replans_north_without_repeating_right(controller):
    s, terrain = route103(controller)
    strategy = controller.strategy
    strategy.target = stale_exit()
    assert target_options(strategy.target, s, controller.memory, terrain) == {}
    options = strategy.options(s, terrain)
    assert list(options) == ["up"]
    assert strategy.target["destination_key"] == "08:05"
    assert strategy.target["cell"][1] == 0
    assert strategy.future is None
    assert not controller.paused
    assert controller.memory.experience.failures(11)[0]["target"] == stale_exit()["id"]
    assert controller.route.now == 11  # Movement plans do not complete milestones.


def test_geometry_supersedes_conflicting_memories_for_the_same_exit(controller):
    s, terrain = route103(controller)
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]["destination_key"] == "08:05"
    gates = [task for task in tasks if task.get("destination_key") == "09:08"]
    assert len(gates) == 1
    assert gates[0]["id"].startswith("geometry:")
    assert gates[0]["direction"] == ""


def test_failed_boundary_direction_is_excluded_before_planning(controller):
    s, terrain = route103(controller)
    controller.memory.move_result("08:04", (11, 0), "up", (11, 0))
    tasks = candidates(s, controller.memory, terrain)
    assert all(task.get("destination_key") != "08:05" for task in tasks)


def test_blocked_remembered_exit_is_excluded_without_cartridge_geometry(controller):
    s, terrain = route103(controller)
    s.map_exits = ()
    controller.strategy.data["connections"] = controller.strategy.data["connections"][1:]
    assert all(task["id"] != stale_exit()["id"]
               for task in candidates(s, controller.memory, terrain))


def test_warp_observation_does_not_reuse_previous_rightward_heading(controller):
    s, _ = route103(controller)
    observations = controller.strategy.observations
    observations.last_direction = "right"
    s.map_group, s.map_number = 9, 8
    s.x, s.y = 5, 1
    s.map_exits = ()
    observations.observe(s, (), overworld=True, milestone=11)
    assert observations.data["connections"][-1]["direction"] == ""
    assert observations.last_direction == ""


def test_current_objective_summary_ignores_incidental_latest_dialogue(controller):
    route103(controller)
    clues = [
        {"text": "The road to TEKNOS is ahead.", "map": "08:04"},
        {"text": "learning than just reading books!", "map": "09:08"},
    ]
    controller.strategy.data["clues"] = clues
    assert controller.strategy.summary()["known"] == clues[0]["text"]
    controller.strategy.data["clues"] = clues[1:]
    assert controller.strategy.summary()["known"] == "No clues for this objective yet"
    assert controller.strategy.data["clues"] == clues[1:]


def test_live_restore_reinstates_route_before_observation_can_overwrite_it(controller, tmp_path):
    from jpp.live import _restore_agent
    from jpp.journey import Journey

    s, terrain = route103(controller)
    controller.memory.checkpoint("route103")
    controller.memory.reset()
    controller.route = RouteProgress()
    journey = Journey("restore-test", tmp_path / "journey.sqlite")
    try:
        _restore_agent(controller, "route103", journey)
        assert controller.route.now == 11
        assert journey.route is controller.route
        controller.route = journey.route  # The live loop shares the UI route.
        controller.observe(s, (), True, terrain)
        assert controller.memory.world["route"]["completed"] == list(range(1, 11))
    finally:
        journey.close()
