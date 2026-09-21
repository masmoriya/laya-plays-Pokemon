"""Offline contract tests; scripted providers are test doubles, not gameplay."""

import json
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.journey_knowledge import knowledge
from jpp.agent.journey_strategy_provider import JourneyStrategyProvider, validate_plan
from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


def state():
    return SimpleNamespace(map_group=9, map_number=2, x=1, y=1,
                           map_width=6, map_height=6, area_name="Pagota City",
                           in_battle=False, badge_ids=(1,), party=(), screen_lines=(),
                           battle=SimpleNamespace(kind="none", opponent=None))


def sprite(x=3, y=1):
    return SimpleNamespace(key="npc:bill-unknown", pixel_x=x * 16, pixel_y=y * 16)


@pytest.fixture
def controller(tmp_path):
    owner = Gold97Controller("strategy-test", database=tmp_path / "agent.sqlite",
                             vision_enabled=False)
    owner.route = RouteProgress(set(range(1, 6)))
    owner.memory.world["route"] = owner.route.to_dict()
    yield owner
    owner.close()


def test_npcs_precede_departure_and_unknown_identity_is_not_invented(controller):
    s = state()
    controller.strategy.observe(s, (sprite(),), True)
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    tasks = candidates(s, controller.memory, terrain)
    assert tasks and all(task["kind"] == "talk" for task in tasks)
    assert controller.strategy.summary()["goal"] == "Visit Bill after beating Falkner"
    assert "Bill" not in tasks[0]["label"]


def test_pressing_a_is_not_conversation_completion_and_pages_persist(controller):
    s = state()
    observations = controller.strategy.observations
    observations.observe(s, (sprite(),), overworld=True, milestone=6)
    identifier = next(iter(observations.data["npcs"]))
    observations.interacted(identifier)
    for _ in range(91):
        observations.observe(s, (), overworld=True, milestone=6)
    assert observations.data["npcs"][identifier]["status"] == "pending"
    observations.interacted(identifier)
    s.screen_lines = ("BILL lives in this town.",)
    for _ in range(14):
        observations.observe(s, (), overworld=False, milestone=6)
    observations.observe(s, (), overworld=True, milestone=6)
    assert observations.data["npcs"][identifier]["status"] == "talked"
    assert len(observations.data["clues"]) == 1
    controller.memory.checkpoint("talked")
    observations.observe(s, (sprite(4, 1),), overworld=True, milestone=6)
    assert len(observations.data["npcs"]) == 1
    controller.memory.restore("talked")
    assert knowledge(controller.memory)["npcs"][identifier]["status"] == "talked"
    observations.observe(s, (sprite(),), overworld=True, milestone=7)
    assert observations.data["npcs"][identifier]["status"] == "talked"


def test_toggle_cancels_pending_plans_and_screen_calls_without_erasing_facts(controller):
    strategy = controller.strategy
    strategy.data["clues"].append({"id": "clue:0", "text": "A clue", "map": "09:02"})
    strategy.toggle()
    strategy.future = Future()
    strategy.future.set_running_or_notify_cancel()
    pending = strategy.future
    controller.vision_future = Future()
    screen = controller.vision_future
    strategy.toggle()
    pending.set_result(({"target": "invalid", "explanation": "stale"}, {}))
    assert not strategy.enabled and strategy.future is None
    assert screen.cancelled()
    assert controller._screen(state(), None) is None
    assert strategy.data["plan"] is None
    assert len(strategy.data["clues"]) == 1


def test_luna_off_does_not_invoke_planner(controller):
    class ForbiddenProvider:
        def plan(self, payload):
            raise AssertionError("Luna Off must not call the planner")

    controller.strategy.provider = ForbiddenProvider()
    s = state()
    controller.strategy.observe(s, (sprite(),), True)
    options = controller.strategy.options(s, Gold97CollisionMap((9, 2), 6, 6, bytes(36)))
    assert options
    assert controller.strategy.future is None
    assert controller.strategy.data["plan"] is None


def test_fresh_luna_plan_after_toggle_and_no_stale_goal(controller):
    class Planner:
        def plan(self, payload):
            target = payload["candidates"][0]
            return {"target": target["id"], "explanation": "Ask this sprite for clues",
                    "evidence": [target["id"]], "completion": "fabricated"}, {"input_tokens": 10}

    strategy = controller.strategy
    strategy.provider = Planner()
    strategy.toggle()
    s = state()
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    strategy.observe(s, (sprite(),), True)
    assert strategy.options(s, terrain) == {}
    strategy.future.result(timeout=1)
    assert strategy.options(s, terrain)
    assert strategy.data["plan"]["completion"] == "Dialogue observed and closed"
    assert controller.route.now == 6
    controller.route.confirm()
    strategy.observe(s, (), True)
    assert strategy.target is None and strategy.data["plan"] is None
    assert controller.opening_goal is None


def test_four_failed_recoveries_pause_and_successful_subgoal_resets(controller):
    strategy = controller.strategy
    strategy.failed("loop one")
    assert not controller.paused
    strategy.failed("loop two")
    assert not controller.paused
    strategy.failed("loop three")
    strategy.failed("loop four")
    assert controller.paused
    assert controller.held_action is None
    assert strategy.data["stats"]["luna_off"]["loop_recovery"] == 4


def test_known_completed_tower_exit_replaces_climb(controller):
    s = state()
    s.map_group, s.map_number = 3, 5
    terrain = Gold97CollisionMap((3, 5), 6, 6, bytes(36))
    controller.strategy.observe(s, (), True)
    tasks = candidates(s, controller.memory, terrain)
    assert len(tasks) == 1 and tasks[0]["kind"] == "exit"
    assert tasks[0]["cell"] == [5, 5]


def test_invalid_target_or_evidence_rejected():
    payload = {"candidates": [{"id": "npc:1", "completion": "Observed dialogue"}], "clues": []}
    plan = {"target": "unknown-house", "explanation": "Go there", "completion": "Done", "evidence": []}
    with pytest.raises(ValueError):
        validate_plan(plan, payload)
    plan.update(target="npc:1", evidence=["imagined-clue"])
    with pytest.raises(ValueError):
        validate_plan(plan, payload)


def test_strategy_provider_exposes_the_exact_prompt_and_schema():
    payload = {
        "goal": "Reach the next town",
        "map": "Silent Town",
        "candidates": [{"id": "exit:1", "completion": "Map changed"}],
        "clues": [],
        "interactions": [],
        "connections": [],
        "recent": [],
        "questions": ["Which exit advances the goal?"],
    }
    model_input = JourneyStrategyProvider(model="test-luna").model_input(payload)
    assert model_input["model"] == "test-luna"
    assert json.dumps(payload) in model_input["prompt"]
    assert model_input["output_schema"]["properties"]["target"]["enum"] == ["exit:1"]


def test_additive_save_and_preference_survive_reopen(tmp_path):
    path = tmp_path / "save.sqlite"
    memory = Gold97Memory("run", path)
    memory.visited("09:02", (1, 1))
    knowledge(memory)["enabled"] = False
    memory.save()
    memory.close()
    memory = Gold97Memory("run", path)
    assert not knowledge(memory)["enabled"]
    assert memory.map("09:02")["visited"] == [[1, 1]]
    memory.close()


def test_no_story_target_is_invented_without_reachable_map_evidence(controller):
    s = state()
    s.map_width, s.map_height = 40, 36
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    controller.strategy.observe(s, (), True)
    assert all(c["kind"] == "explore" for c in candidates(s, controller.memory, terrain))
    controller.memory.map("09:02")["visited"] = [[x, y] for y in range(36) for x in range(40)]
    assert not candidates(s, controller.memory, terrain)
    s.mechanics_verified = True
    assert not candidates(s, controller.memory, terrain)


def test_goal_terms_rank_matching_map_without_a_story_specific_override(controller):
    s = state()
    s.map_width, s.map_height = 40, 36
    s.mechanics_verified = True
    s.map_exits = ((30, 22, "up", 9, 14), (27, 28, "up", 9, 7))
    controller.strategy.observe(s, (sprite(24, 18),), True)
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]["destination"] == "Bills Familys House"
    assert tasks[0]["cell"] == [30, 22]
    assert tasks[0]["journey_reward"] >= 100
    assert not tasks[0]["id"].startswith("guide:")


def test_after_milestone_exit_outranks_unrelated_conversation(controller):
    controller.route.completed.add(6)
    controller.memory.world["route"] = controller.route.to_dict()
    s = state()
    s.map_group, s.map_number = 9, 14
    s.map_width, s.map_height = 8, 8
    s.area_name = "Bills Familys House"
    s.x, s.y = 5, 5
    s.mechanics_verified = True
    family = sprite(2, 3)
    family.key = "object:2"
    controller.strategy.observe(s, (family,), True)
    controller.strategy.data["connections"] = [
        {"from": "09:0E", "at": [4, 7], "to": "09:02",
         "arrival": [30, 22], "direction": "down"},
    ]
    terrain = Gold97CollisionMap((9, 14), 8, 8, bytes(64))
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]["kind"] == "exit"
    assert tasks[0]["journey_reward"] > next(
        task["journey_reward"] for task in tasks if task["kind"] == "talk")


def test_active_goal_reward_targets_route_102_before_npcs_and_services(controller):
    controller.route.completed.add(6)
    controller.memory.world["route"] = controller.route.to_dict()
    s = state()
    s.map_width, s.map_height = 40, 36
    s.x, s.y = 23, 22
    s.mechanics_verified = True
    s.map_exits = (tuple((0, y, "left", 9, 1) for y in range(36))
                   + ((27, 28, "up", 9, 7),))
    controller.strategy.observe(s, (sprite(24, 18),), True)
    terrain = Gold97CollisionMap((9, 2), 40, 36, bytes(1440))
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]["destination"] == "Route 102"
    assert tasks[0]["cell"][0] == 0
    assert tasks[0]["journey_reward"] >= 100
    center = next(task for task in tasks if task.get("destination") == "Pagota Pokémon Center 1F")
    assert center["journey_reward"] == 0


def test_route_goal_prefers_progress_gate_over_optional_route_house(controller):
    controller.route.completed.add(6)
    controller.memory.world["route"] = controller.route.to_dict()
    s = state()
    s.map_group, s.map_number = 9, 1
    s.area_name = "Route 102"
    s.map_width, s.map_height = 64, 16
    s.x, s.y = 26, 6
    s.mechanics_verified = True
    s.map_exits = ((6, 5, "up", 9, 10), (16, 4, "up", 9, 15))
    terrain = Gold97CollisionMap((9, 1), 64, 16, bytes(1024))
    tasks = candidates(s, controller.memory, terrain)
    gate = next(task for task in tasks if "Westport Gate" in task.get("destination", ""))
    house = next(task for task in tasks if "N64 House" in task.get("destination", ""))
    assert gate["journey_reward"] > house["journey_reward"]


@pytest.mark.parametrize(("map_number", "position"), (
    (7, (5, 4)),
    (1, (5, 4)),
))
def test_exit_reward_outranks_npcs_in_center_and_link_floor(
        controller, map_number, position):
    data = controller.strategy.data
    data["connections"] = [
        {"from": "09:02", "at": [27, 28], "to": "09:07",
         "arrival": [5, 7], "direction": "up"},
        {"from": "09:07", "at": [0, 7], "to": "11:01",
         "arrival": [0, 7], "direction": "left"},
    ]
    key = f"{17 if map_number == 1 else 9:02X}:{map_number:02X}"
    data["npcs"][f"{key}/object:1"] = {
        "id": f"{key}/object:1", "map": key, "cell": [6, 4],
        "status": "pending", "visible": True, "attempts": 0,
        "milestone": 6, "pages": [],
    }
    s = state()
    s.map_group = 17 if map_number == 1 else 9
    s.map_number = map_number
    s.area_name = "Pokecenter 2F" if map_number == 1 else "Pagota Pokemon Center 1F"
    s.x, s.y = position
    s.map_width, s.map_height = 16, 8
    s.mechanics_verified = True
    terrain = Gold97CollisionMap((s.map_group, map_number), 16, 8, bytes(128))
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]["kind"] == "exit"
    assert tasks[0]["journey_reward"] > next(
        task["journey_reward"] for task in tasks if task["kind"] == "talk")


def test_restore_invalidates_pending_answer_and_resets_observation_origin(controller):
    strategy = controller.strategy
    strategy.observe(state(), (), True)
    controller.memory.checkpoint("old")
    strategy.future = Future()
    pending = strategy.future
    controller.memory.restore("old")
    strategy.observe(state(), (), True)
    assert pending.cancelled()
    assert strategy.future is None
    assert strategy.observations.data["connections"] == []


def test_stale_completed_luna_usage_is_counted_without_applying_plan(controller):
    strategy = controller.strategy
    strategy.toggle()
    pending = Future()
    pending.set_running_or_notify_cancel()
    strategy.future = pending
    strategy.toggle()
    pending.set_result(({"target": "stale"}, {"input_tokens": 25, "output_tokens": 3}))
    strategy.poll_retired()
    assert strategy.data["plan"] is None
    assert controller.usage_snapshot()["luna"]["input_tokens"] == 25


def test_checkpoint_restore_never_reenables_disabled_luna(controller):
    controller.strategy.toggle()
    controller.memory.checkpoint("luna-on")
    controller.strategy.toggle()
    assert not controller.strategy.enabled
    controller.memory.restore("luna-on")
    assert not controller.strategy.enabled
    controller.memory.reset()
    assert not controller.strategy.enabled


def test_discovery_does_not_interrupt_a_committed_route_or_mark_an_obstacle(controller):
    s = state()
    controller.strategy.observe(s, (), True)
    controller.strategy.target = {
        "id": "guide:committed", "kind": "exit", "cell": [4, 1],
        "direction": "right",
    }
    controller.last = ("09:02", (1, 1), "right")
    controller.held_action = "right"
    controller.cooldown = 3
    controller.strategy.observe(s, (sprite(),), True)
    controller._observe_move(s)
    assert controller.last == ("09:02", (1, 1), "right")
    assert controller.held_action == "right"
    assert controller.memory.map("09:02")["blocked"] == []


def test_stale_blocked_exits_are_rechecked_once(controller):
    s = state()
    strategy = controller.strategy
    strategy.observe(s, (), True)
    strategy.data['enabled'] = False
    controller.memory.visited('09:02', (s.x, s.y))
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
    area = controller.memory.map('09:02')
    blocked = [[[s.x, s.y], direction] for direction in ('up', 'down', 'left', 'right')]
    area['blocked'] = blocked.copy()
    assert not candidates(s, controller.memory, terrain)
    assert strategy.options(s, terrain)
    assert not controller.paused
    assert not area['blocked']
    # If attempts really fail again, stop instead of endlessly retrying.
    area['blocked'] = blocked.copy()
    assert not strategy.options(s, terrain)
    assert controller.paused
    controller.resume()
    assert strategy.options(s, terrain)
    assert not controller.paused


def test_blocked_exit_retry_preserves_cartridge_walls(controller):
    s = state()
    strategy = controller.strategy
    strategy.observe(s, (), True)
    strategy.data['enabled'] = False
    controller.memory.visited('09:02', (s.x, s.y))
    terrain = Gold97CollisionMap((9, 2), 6, 6, bytes([7] * 36))
    controller.memory.map('09:02')['blocked'] = [[[s.x, s.y], 'up']]
    assert not strategy.options(s, terrain)
    assert controller.paused
