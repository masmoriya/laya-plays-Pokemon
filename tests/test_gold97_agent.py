from types import SimpleNamespace
from threading import Event
from concurrent.futures import Future

import numpy as np

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_navigation import frontier_step
from jpp.agent.providers.jev_provider import JevProvider
from jpp.agent.old_species import ORIGINAL_251, hack_exclusive
from jpp.agent.policy_adapter import ProviderPolicy
from jpp.policy import Decision


def _state(*, battle="none", foe=None, caught=()):
    return SimpleNamespace(
        map_group=20, map_number=4, x=3, y=5, map_width=10, map_height=10,
        area_name="Silent Town", in_battle=battle != "none", party=(),
        badge_ids=(), pokedex_caught_ids=caught,
        battle=SimpleNamespace(kind=battle, opponent=foe),
    )


def test_original_species_guard_is_name_based():
    assert len(ORIGINAL_251) == 251
    assert not hack_exclusive("CHIKORITA")
    assert not hack_exclusive("HO-OH")
    assert not hack_exclusive("Mewtwo")
    assert not hack_exclusive("NIDORAN♀")
    assert hack_exclusive("FLAMBEAR")
    assert not hack_exclusive("FLAMBEAR", verified_rom=False)
    assert not hack_exclusive("UNKNOWN")


def test_jev_provider_uses_real_closed_set_policy():
    class Policy:
        client = SimpleNamespace(model="test-jev")

        def decide(self, branch):
            assert branch.options == {"up": "walk north"}
            assert branch.state["decision_kind"] == "explore"
            return Decision(option="up", probabilities={"up": 1.0}, confidence=1.0)

    result = JevProvider(Policy()).decide_tactical(
        {"decision_kind": "explore"}, {"up": "walk north"})
    assert result["action"] == "up"
    assert result["probabilities"] == {"up": 1.0}


def test_world_memory_restores_checkpoint(tmp_path):
    database = tmp_path / "agent.sqlite"
    memory = Gold97Memory("run", database)
    memory.visited("14:04", (3, 5))
    memory.move_result("14:04", (3, 5), "up", (3, 4))
    memory.remember("clue", "Door opens after a badge", "14:04")
    memory.checkpoint("before-encounter")
    memory.move_result("14:04", (3, 4), "left", (3, 4))
    assert memory.map("14:04")["blocked"]
    assert memory.restore("before-encounter")
    assert not memory.map("14:04")["blocked"]
    assert memory.relevant("14:04")[0]["value"] == "Door opens after a badge"
    memory.close()


def test_navigator_uses_only_confirmed_edges():
    area = {"visited": [[0, 0], [1, 0], [1, 1]],
            "edges": [[[0, 0], "right"], [[1, 0], "left"],
                      [[1, 0], "down"], [[1, 1], "up"]],
            "blocked": [[[0, 0], "down"], [[1, 0], "right"]]}
    assert frontier_step(area, (0, 0), 3, 3) == "right"


def test_controller_excludes_failed_move_but_continues_old_wild_battles(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        controller.memory.move_result("14:04", (3, 5), "left", (3, 5))
        assert "left" not in controller._options(state, ())
        foe = SimpleNamespace(species="LUGIA", species_id=249, hp=20)
        assert "a" in controller._options(_state(battle="wild", foe=foe), ())
        assert not controller.paused
    finally:
        controller.close()


def test_unreadable_wild_encounter_waits_without_guessing_run(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite", vision_enabled=False)
    try:
        foe = SimpleNamespace(species="RATTATA", species_id=19, hp=20)
        state = _state(battle="wild", foe=foe)
        state.battle_menu_cursor = (1, 1)
        assert controller.step(state) is None
        assert not controller.paused
    finally:
        controller.close()


def test_trainer_battle_opens_fight_then_navigates_to_move_with_pp(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        active = SimpleNamespace(species="FLAMBEAR", species_id=155,
                                 moves=("TACKLE", "GROWL", "EMBER"),
                                 pp=(0, 10, 5), hp=9, max_hp=32)
        foe = SimpleNamespace(species="PIDGEY", species_id=16, hp=20)
        state = _state(battle="trainer", foe=foe)
        state.party = (active,)
        state.read_oaks_email = False
        state.opening_scene = None
        state.battle.active = active
        state.battle_menu_cursor = (1, 1)
        assert controller.step(state) == "a"  # open FIGHT, never confirm TACKLE
        controller.cooldown = 0
        state.battle_menu_cursor = (1, 2)
        assert controller.step(state) == "down"  # move to EMBER's row
        controller.cooldown = 0
        state.battle_menu_cursor = (1, 3)
        assert controller.step(state) == "a"
        assert controller.battle_target == 2
    finally:
        controller.close()


def test_trainer_attack_text_does_not_navigate_stale_move_cursor(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        active = SimpleNamespace(species="FLAMBEAR", species_id=155,
                                 moves=("TACKLE",), pp=(20,), hp=30, max_hp=36)
        foe = SimpleNamespace(species="PIDGEY", species_id=16, hp=20)
        state = _state(battle="trainer", foe=foe)
        state.battle.active = active
        state.battle_menu_kind = "text"
        state.battle_menu_cursor = (1, 4)  # stale RAM, not a visible menu
        assert controller._trainer_battle_action(state) == "a"
    finally:
        controller.close()


def test_trainer_faint_clears_party_error_then_selects_healthy_replacement(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        fainted_one = SimpleNamespace(slot=1, species="TANGTRIP", hp=0, max_hp=26,
                                      level=8, moves=(), pp=())
        fainted_two = SimpleNamespace(slot=2, species="HOPPIP", hp=0, max_hp=26,
                                      level=8, moves=(), pp=())
        healthy = SimpleNamespace(slot=3, species="VOLBEAR", hp=53, max_hp=53,
                                  level=18, moves=("BITE",), pp=(25,))
        state = _state(battle="trainer", foe=SimpleNamespace(species="SPEAROW",
                                                               types=("FLYING",), hp=30))
        state.party = (fainted_one, fainted_two, healthy)
        state.battle.active = fainted_two
        state.battle_menu_kind = "party"
        state.battle_menu_cursor = (1, 2)
        state.screen_lines = ("",) * 14 + ("There no will to", "", "battle.", "")
        assert controller.step(state) == "a"

        controller.cooldown = 0
        state.screen_lines = ("",) * 14 + ("", "", "Which ?", "")
        assert controller.step(state) == "down"

        controller.cooldown = 0
        state.battle_menu_cursor = (1, 3)
        assert controller.step(state) == "a"
        assert controller.battle_switch_phase == "wait"

        controller.cooldown = 0
        assert controller.step(state) is None
    finally:
        controller.close()


def test_trainer_level_up_moves_to_replacement_instead_of_confirming_ember(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        active = SimpleNamespace(species="FLAMBEAR", species_id=155,
                                 moves=("EMBER", "SCRATCH", "SAND ATTACK", "GROWL"),
                                 pp=(20, 30, 15, 30), types=("FIRE",), hp=24, max_hp=32)
        foe = SimpleNamespace(species="PIDGEY", species_id=16, hp=0)
        state = _state(battle="trainer", foe=foe)
        state.party = (active,)
        state.battle.active = active
        state.battle_menu_kind = "text"
        state.screen_lines = ("FLAMBEAR is trying", "to learn BITE!")
        state.screen_cursor = None
        assert controller.step(state) == "a"
        assert controller.learning_move == "Bite"
        controller.cooldown = 0
        state.screen_lines = ("EMBER", "SCRATCH", "SAND ATTACK", "GROWL", "CANCEL")
        state.screen_cursor = (1, 0)
        assert controller.step(state) == "down"
        assert not controller.paused
    finally:
        controller.close()


def test_unreadable_level_up_menu_pauses_instead_of_deleting_a_move(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        active = SimpleNamespace(species="FLAMBEAR", species_id=155,
                                 moves=("EMBER", "SCRATCH", "SAND ATTACK", "GROWL"),
                                 pp=(20, 30, 15, 30), types=("FIRE",), hp=24, max_hp=32)
        state = _state(battle="trainer", foe=SimpleNamespace(species="PIDGEY", hp=0))
        state.party = (active,)
        state.battle.active = active
        state.battle_menu_kind = "text"
        state.screen_lines = ("EMBER", "SCRATCH", "SAND ATTACK", "GROWL", "CANCEL")
        state.screen_cursor = (1, 0)
        assert controller.step(state) is None
        assert controller.paused
        assert "missing its move" in controller.pause_reason
    finally:
        controller.close()


def test_low_hp_in_tower_retreats_to_center_without_opening_pack(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        state = _state()
        state.map_group, state.map_number = 3, 1
        state.area_name = "Brass Tower 1F"
        state.x, state.y, state.map_width, state.map_height = 5, 10, 12, 12
        state.party = (SimpleNamespace(hp=14, max_hp=36),)
        state.potion_count = 2
        assert controller._recovery_action(state, overworld=True) == "down"
        assert controller.healing is None
        assert controller.recovery is not None
    finally:
        controller.close()


def test_center_exit_keeps_walking_through_doorway(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        state = _state()
        state.map_group, state.map_number = 9, 7
        state.area_name = "Pagota Pokémon Center 1F"
        state.x, state.y, state.map_width, state.map_height = 5, 7, 16, 8
        state.party = (SimpleNamespace(hp=34, max_hp=34),)
        controller.recovery = {"exit": True}
        assert controller._recovery_action(state, overworld=True) == "down"
    finally:
        controller.close()


def test_center_transition_does_not_press_a_before_prompt_is_visible(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        state = _state()
        state.map_group, state.map_number = 9, 7
        state.area_name = "Pagota Pokémon Center 1F"
        state.x, state.y, state.map_width, state.map_height = 5, 7, 16, 8
        state.party = (SimpleNamespace(hp=10, max_hp=34),)
        controller.recovery = {"started": True, "attempts": 0}
        assert controller._recovery_action(
            state, overworld=False, prompt_visible=False) is None
        assert controller._recovery_action(
            state, overworld=False, prompt_visible=True) == "a"
    finally:
        controller.close()


def test_center_exit_transition_does_not_close_a_loading_room(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        state = _state()
        state.map_group, state.map_number = 9, 2
        state.area_name = "Pagota City"
        state.x, state.y = 27, 28
        state.party = (SimpleNamespace(hp=34, max_hp=34),)
        controller.recovery = {"started": True, "attempts": 0, "exit": True}
        assert controller._recovery_action(
            state, overworld=False, prompt_visible=False) is None
        assert controller.recovery is None
    finally:
        controller.close()


def test_capture_switches_from_items_to_balls_without_using_potion(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        foe = SimpleNamespace(species="FLAMBEAR", species_id=155, hp=12)
        state = _state(battle="wild", foe=foe)
        state.party = (SimpleNamespace(species_id=152, hp=25, max_hp=30),)
        state.poke_ball_count = 3
        state.battle_menu_kind = "text"
        state.battle_menu_cursor = None
        state.screen_lines = ("POTION", "CANCEL")
        state.screen_cursor = (5, 3)
        assert controller._capture_action(state) == "right"
        state.screen_lines = ("POK  BALL", "CANCEL")
        state.screen_cursor = (5, 0)
        assert controller._capture_action(state) == "a"
        state.screen_lines = ("POK  BALL", "USE", "CANCEL")
        assert controller._capture_action(state) == "a"
        controller.capture["phase"] = "escape"
        assert controller._capture_action(state) == "b"
    finally:
        controller.close()


def test_journey_milestone_persists_with_controller_memory(tmp_path):
    database = tmp_path / "agent.sqlite"
    controller = Gold97Controller("run", database=database)
    try:
        state = _state()
        state.map_number = 2
        state.area_name = "Route 101"
        state.party = (SimpleNamespace(species="FLAMBEAR"),)
        state.map_width, state.map_height = 52, 38
        controller.step(state)
        assert controller.route.now == 3
    finally:
        controller.close()
    resumed = Gold97Controller("run", database=database)
    try:
        assert resumed.route.now == 3
    finally:
        resumed.close()


def test_overworld_does_not_offer_a_for_an_unknown_sprite(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        options = controller._options(state, ())
        assert "a" not in options
        adjacent = SimpleNamespace(pixel_x=state.x * 16 + 16, pixel_y=state.y * 16)
        assert "a" not in controller._options(state, (adjacent,))
        controller.last_move_direction = "right"
        assert "left" not in controller._options(state, ())
    finally:
        controller.close()


def test_unavailable_laya_pauses_without_local_movement(tmp_path):
    class OfflineLaya:
        usage_provider = "laya"

        def decide_tactical(self, state, options):
            assert "a" not in options
            raise ConnectionError("sidecar offline")

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(OfflineLaya()), vision_enabled=False,
    )
    try:
        state = _state()
        adjacent = SimpleNamespace(pixel_x=state.x * 16 + 16,
                                   pixel_y=state.y * 16)
        assert controller.step(state, entities=(adjacent,), overworld=True) is None
        controller.decision_future.result(timeout=1)
        assert controller.step(state, entities=(adjacent,), overworld=True) is None
        assert controller.paused
        assert controller.held_action is None
    finally:
        controller.close()


def test_room_transition_without_dialogue_does_not_press_a(tmp_path):
    class Laya:
        usage_provider = "laya"

        def decide_tactical(self, state, options):
            assert options == {"a": "advance current dialogue"}
            return {"action": "a"}

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(Laya()), vision_enabled=False,
    )
    try:
        state = _state()
        state.map_group, state.map_number = 3, 2
        state.area_name = "Brass Tower 2F"
        state.party = (SimpleNamespace(species="FLAMBEAR", level=8, hp=30,
                                       max_hp=30, types=(), moves=(), pp=(),
                                       status="none"),)
        state.pokedex_species = ()
        state.battle.active = None
        state.screen_lines = ("", "", "BRASS TOWER") + ("",) * 15
        state.screen_cursor = None
        controller.unknown_frames = 8

        party = state.party
        state.party = ()  # Party RAM can be briefly incomplete during a warp.
        assert controller.step(state, overworld=False) is None
        assert not controller.title_bootstrap_done
        state.party = party
        assert controller.step(state, overworld=False) is None
        assert controller.decision_future is None
        assert controller.cooldown == 0

        state.screen_lines = ("",) * 14 + ("Please come in",) + ("",) * 3
        assert controller.step(state, overworld=False) is None
        controller.decision_future.result(timeout=1)
        assert controller.step(state, overworld=False) == "a"
    finally:
        controller.close()


def test_stale_text_does_not_trigger_a_without_a_visible_prompt(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        state = _state()
        state.map_group, state.map_number = 3, 4
        state.screen_lines = ("",) * 14 + ("QQ bQ QQ",) + ("",) * 3
        controller.unknown_frames = 8
        assert controller.step(state, overworld=False, prompt_visible=False) is None
        assert controller.decision_future is None
        assert controller.cooldown == 0
    finally:
        controller.close()


def test_play_resume_releases_old_cooldown_and_walks(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        controller.route.completed.update({1, 2, 3})
        controller.cooldown = 45
        stale = Future()
        controller.decision_future = stale
        controller.decision_key = ("before pause",)
        controller.pause("manual")
        state = _state()
        state.map_group, state.map_number = 3, 2
        state.x, state.y = 0, 1
        state.map_width = state.map_height = 12
        controller.resume()
        assert stale.cancelled()
        assert controller.decision_future is None
        assert controller.step(state, overworld=True) in {"right", "down"}
    finally:
        controller.close()


def test_laya_health_check_gates_autonomous_movement(tmp_path):
    release_health = Event()

    class SlowLaya:
        usage_provider = "laya"

        def health(self):
            release_health.wait(timeout=1)
            return {"status": "ok"}

        def decide_tactical(self, state, options):
            raise AssertionError("decision must not queue behind health")

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(SlowLaya()), vision_enabled=False,
    )
    try:
        state = _state()
        state.map_group, state.map_number = 9, 2
        assert controller.provider_health == "checking"
        assert controller.step(state, overworld=True) is None
        assert controller.held_action is None
        assert controller.decision_future is None
    finally:
        release_health.set()
        controller.close()


def test_interaction_tiles_do_not_block_a_new_map(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        controller.route.completed.update({1, 2, 3})
        controller.interaction_map_key = (9, 2)
        controller.interaction_positions.add((0, 2))
        state = _state()
        state.map_group, state.map_number = 3, 2
        state.area_name = "Brass Tower 2F"
        state.x, state.y = 0, 1
        state.map_width, state.map_height = 12, 12

        assert controller.step(state, overworld=True) == "down"
        assert controller.interaction_positions == set()
    finally:
        controller.close()


def test_tower_route_moves_past_adjacent_sprite_after_stair_warp(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  vision_enabled=False)
    try:
        controller.route.completed.update({1, 2, 3})
        state = _state()
        state.map_group = 3
        state.map_number = 2
        state.x, state.y = 0, 1
        state.map_width, state.map_height = 12, 12
        adjacent = SimpleNamespace(pixel_x=state.x * 16 + 16,
                                   pixel_y=state.y * 16)

        # The stair landing is next to a visible sprite, but the tower route
        # must keep walking toward the next stair instead of pressing A.
        assert controller.step(state, entities=(adjacent,), overworld=True) in {
            "right", "down"
        }
    finally:
        controller.close()


def test_dialogue_without_menu_cursor_advances_forward(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        assert controller._options(_state(), (), overworld=False) == {
            "a": "advance current dialogue"
        }
    finally:
        controller.close()


def test_players_house_exit_keeps_laya_on_verified_doorway(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        state.map_number = 7
        state.x = 9
        state.y = 1
        assert controller._options(state, ()) == {"left": "walk left toward (8, 1)"}
    finally:
        controller.close()


def test_overworld_prefers_unexplored_neighbors(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        controller.memory.visited("14:04", (state.x + 1, state.y))
        assert "right" not in controller._options(state, ())
    finally:
        controller.close()


def test_completed_dialogue_tile_is_not_reentered_when_an_exit_path_exists(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        controller.interaction_positions.add((state.x, state.y - 1))
        options = controller._options(state, ())
        assert "up" not in options
    finally:
        controller.close()


def test_laya_controller_uses_legal_choice_and_records_laya_usage(tmp_path):
    class Laya:
        usage_provider = "laya"
        model = "test-laya"

        def decide_tactical(self, state, options):
            return {
                "action": "up",
                "confidence": 0.08,
                "input_tokens": 7,
                "model_input": {
                    "state": state,
                    "questions": {"next_action": {"criteria": options}},
                },
            }

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(Laya()), vision_enabled=False,
    )
    try:
        state = _state()
        assert controller.step(state, overworld=True) is None
        controller.decision_future.result(timeout=1)
        assert controller.step(state, overworld=True) == "up"
        controller.cooldown = 0
        usage = controller.usage_snapshot()
        assert usage["laya"]["calls"] == 1
        assert usage["jev"]["calls"] == 0
        assert controller.latest_model_input["provider"] == "Laya"
        assert controller.pop_provider_event().startswith("Laya input ·")
        assert controller.pop_provider_event() == "Laya chose up"
        controller.last = ("14:04", (state.x, state.y), "up")
        controller._observe_move(state)
        assert controller.pop_provider_event() == "Blocked up at 3,5"
    finally:
        controller.close()


def test_laya_health_is_ready_without_luna_or_jev(tmp_path):
    class Laya:
        usage_provider = "laya"
        model = "test-laya"

        def health(self):
            return {"status": "ok", "model": "test-laya"}

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(Laya()), vision_enabled=False,
    )
    try:
        controller.provider_health_future.result(timeout=1)
        controller._poll_provider_health()
        assert controller.provider_health == "ready"
        assert controller.pop_provider_event() is None
        controller._start_provider_health_check()
        assert controller.provider_health == "ready"
        controller.provider_health_future.result(timeout=1)
        controller._poll_provider_health()
        assert controller.pop_provider_event() is None
    finally:
        controller.close()


def test_movement_hold_replans_immediately_after_tile_lands(tmp_path):
    class Laya:
        usage_provider = "laya"

        def decide_tactical(self, state, options):
            return {"action": "up", "confidence": 0.08}

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(Laya()), vision_enabled=False,
    )
    try:
        state = _state()
        controller.last = ("14:04", (state.x, state.y), "up")
        controller.held_action = "up"
        controller.cooldown = 36
        controller._observe_move(state)
        assert controller.held_action == "up"
        state.y -= 1
        controller._observe_move(state)
        assert controller.held_action == "up"
        assert controller.cooldown == 0
    finally:
        controller.close()


def test_repeated_unresponsive_moves_replan_without_pausing(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        for _ in range(8):
            controller.last = ("14:04", (state.x, state.y), "down")
            controller.cooldown = 0
            controller._observe_move(state)
        assert not controller.paused
        assert controller.stalls == 0
        assert controller.replans_at[("14:04", (state.x, state.y))] == 1
        events = iter(controller.pop_provider_event, None)
        assert any("Replanning" in event for event in events)
    finally:
        controller.close()


def test_stalled_bedroom_replans_without_rewinding(tmp_path):
    restored = []
    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        restore_stuck=lambda: restored.append("earlier.state") or "earlier.state",
    )
    try:
        state = _state()
        state.map_number = 7
        state.read_oaks_email = False
        for _ in range(8):
            controller.last = ("14:07", (state.x, state.y), "down")
            controller.cooldown = 0
            controller._observe_move(state)
        assert restored == []
        assert controller.stuck_restores == 0
        assert not controller.paused
        assert controller.replans_at[("14:07", (state.x, state.y))] == 1
    finally:
        controller.close()


def test_laya_health_failure_reports_error_without_blocking_local_goals(tmp_path):
    class Laya:
        usage_provider = "laya"

        def health(self):
            raise RuntimeError("connection refused")

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(Laya()), vision_enabled=False,
    )
    try:
        try:
            controller.provider_health_future.result(timeout=1)
        except RuntimeError:
            pass
        controller._poll_provider_health()
        assert controller.provider_health == "unavailable"
        assert not controller.paused
        assert "Laya unavailable" in controller.pop_provider_event()
    finally:
        controller.close()


def test_static_encounter_blocks_without_rewinding_when_not_caught(tmp_path):
    restored = []
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  restore_encounter=restored.append)
    try:
        controller.encounter = {"checkpoint": "safe.state", "species_id": 249,
                                "species": "LUGIA", "map": "14:04", "started": True}
        controller.memory.checkpoint("safe.state")
        controller._finish_encounter(_state())
        assert restored == []
        assert controller.paused
        controller.encounter = {"checkpoint": "safe.state", "species_id": 249,
                                "species": "LUGIA", "map": "14:04", "started": True}
        controller._finish_encounter(_state(caught=(249,)))
        assert restored == []
        assert controller.memory.relevant("14:04")[-1]["kind"] == "capture"
    finally:
        controller.close()


def test_luna_only_after_unknown_screen_trigger(tmp_path):
    class Vision:
        calls = 0

        def describe(self, frame):
            self.calls += 1
            return {"mode": "menu", "screen_text": ["CONTINUE", "NEW GAME"],
                    "uncertainty": ""}

    vision = Vision()
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite", vision=vision)
    try:
        state = _state()
        assert controller._options(state, (), overworld=True)
        assert vision.calls == 0
        frame = np.zeros((144, 160, 4), dtype=np.uint8)
        assert controller._screen(state, frame) is None
        controller.vision_future.result(timeout=1)
        assert controller._screen(state, frame)["screen_text"] == ["CONTINUE", "NEW GAME"]
        assert vision.calls == 1
    finally:
        controller.close()


def test_live_footer_exposes_opt_in_play_and_pause():
    import os
    import pygame

    from jpp.live_ui import LiveUI, SIZE

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        ui._footer({"jev_available": True, "jev_auto": False})
        assert "toggle_jev" in ui.actions
        ui._footer({"jev_available": True, "jev_auto": True})
        assert "toggle_jev" in ui.actions
    finally:
        pygame.quit()


def test_wild_faint_selects_stronger_replacement_and_keeps_fighting(tmp_path):
    from jpp.decode import Mon, Battle
    from dataclasses import replace
    active = Mon(slot=1, species='TANGTRIP', species_id=1, level=8,
                 hp=0, max_hp=26, status='none', types=('GRASS',), moves=('ABSORB',), pp=(20,))
    weak = replace(active, slot=2, hp=26, moves=('TACKLE',))
    strong = replace(active, slot=3, species='VOLBEAR', level=20, hp=50,
                     max_hp=59, types=('FIRE',), moves=('EMBER',))
    foe = replace(weak, slot=0, species='RATTATA', types=('NORMAL',))
    st = _state(battle='wild', foe=foe)
    st.battle = Battle('wild', active, foe)
    st.party, st.active_slot = (active, weak, strong), 0
    st.battle_menu_kind, st.battle_menu_cursor = 'party', (1, 1)
    st.screen_lines = ()
    controller = Gold97Controller('replacement', database=tmp_path / 'agent.sqlite',
                                  vision_enabled=False)
    try:
        for cursor, expected in [((1, 1), 'down'), ((1, 2), 'down'), ((1, 3), 'a')]:
            st.battle_menu_cursor = cursor
            controller.cooldown = 0
            assert controller.step(st, overworld=False) == expected
        assert controller.battle_executor.action.target == 2
        st.battle = Battle('wild', strong, foe)
        st.active_slot = 2
        st.battle_menu_kind, st.battle_menu_cursor = 'command', (1, 1)
        controller.cooldown = 0
        assert controller.step(st, overworld=False) == 'a'
        assert controller.battle_executor.action.kind == 'move'
    finally:
        controller.close()


def test_failed_escape_commits_to_battle(tmp_path):
    controller = Gold97Controller('escape', database=tmp_path / 'agent.sqlite',
                                  vision_enabled=False)
    st = _state(battle='wild', foe=SimpleNamespace(species='RATTATA', species_id=19))
    st.screen_lines = ('Can t escape!',)
    st.battle_menu_kind = 'text'
    calls = []
    controller._trainer_battle_action = lambda state: calls.append(state) or 'a'
    try:
        assert controller.step(st, overworld=False) == 'a'
        st.screen_lines = ()
        st.battle_menu_kind = 'command'
        controller.cooldown = 0
        assert controller.step(st, overworld=False) == 'a'
        assert len(calls) == 2
    finally:
        controller.close()
