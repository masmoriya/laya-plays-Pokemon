from types import SimpleNamespace

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


def test_ordinary_wild_encounter_navigates_run_without_model(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        foe = SimpleNamespace(species="RATTATA", species_id=19, hp=20)
        state = _state(battle="wild", foe=foe)
        state.battle_menu_cursor = (1, 1)
        assert controller.step(state) == "right"
        controller.cooldown = 0
        state.battle_menu_cursor = (2, 1)
        assert controller.step(state) == "down"
        controller.cooldown = 0
        state.battle_menu_cursor = (2, 2)
        assert controller.step(state) == "a"
        assert not controller.paused
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


def test_overworld_does_not_offer_a_without_an_interaction(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        options = controller._options(state, ())
        assert "a" not in options
        adjacent = SimpleNamespace(pixel_x=state.x * 16 + 16, pixel_y=state.y * 16)
        assert "a" in controller._options(state, (adjacent,))
        controller.last_move_direction = "right"
        assert "left" not in controller._options(state, ())
    finally:
        controller.close()


def test_unknown_menu_only_advances_forward(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        assert controller._options(_state(), (), overworld=False) == {
            "a": "advance current dialogue or confirm the highlighted menu"
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
            return {"action": "up", "confidence": 0.08, "input_tokens": 7}

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
        assert controller.pop_provider_event() == "Laya sidecar ready"
    finally:
        controller.close()


def test_movement_hold_window_allows_cartridge_step_to_land(tmp_path):
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
        controller.cooldown = 0
        controller._observe_move(state)
        assert controller.held_action is None
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
        assert "Replanning" in controller.pop_provider_event()
    finally:
        controller.close()


def test_stalled_bedroom_restores_one_prior_snapshot(tmp_path):
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
        assert restored == ["earlier.state"]
        assert controller.stuck_restores == 1
        assert not controller.paused
        assert controller.memory.map("14:07")["blocked"] == []
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


def test_static_encounter_restores_when_not_caught(tmp_path):
    restored = []
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite",
                                  restore_encounter=restored.append)
    try:
        controller.encounter = {"checkpoint": "safe.state", "species_id": 249,
                                "species": "LUGIA", "map": "14:04", "started": True}
        controller.memory.checkpoint("safe.state")
        controller._finish_encounter(_state())
        assert restored == ["safe.state"]
        assert controller.cooldown == 20
        controller.encounter = {"checkpoint": "safe.state", "species_id": 249,
                                "species": "LUGIA", "map": "14:04", "started": True}
        controller._finish_encounter(_state(caught=(249,)))
        assert restored == ["safe.state"]
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
