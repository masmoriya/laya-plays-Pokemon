from types import SimpleNamespace

import numpy as np

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_navigation import frontier_step
from jpp.agent.providers.jev_provider import JevProvider
from jpp.agent.old_species import ORIGINAL_251, hack_exclusive
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


def test_controller_excludes_failed_move_and_old_wild_catches(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        state = _state()
        controller.memory.move_result("14:04", (3, 5), "left", (3, 5))
        assert "left" not in controller._options(state, ())
        foe = SimpleNamespace(species="LUGIA", species_id=249, hp=20)
        assert controller._options(_state(battle="wild", foe=foe), ()) == {}
        assert controller.paused
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
