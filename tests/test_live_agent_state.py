import os
from types import SimpleNamespace as NS

import numpy as np
import pygame

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.live_state import LiveAgentState
from jpp.agent.policy_adapter import ProviderPolicy
from jpp.character.animation import Animation
from jpp.live_ui import LiveUI, SIZE


class _LocalLaya:
    usage_provider = "laya"

    def decide_tactical(self, state, options):
        return {"action": next(iter(options)), "request_made": False}


def _state():
    return NS(
        map_group=9, map_number=2, x=3, y=5, map_width=10, map_height=10,
        area_name="Pagota City", in_battle=False, party=(), screen_lines=(),
        battle=NS(kind="none", opponent=None),
    )


def test_operator_guidance_and_lean_context_are_durable_and_scoped(tmp_path):
    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(_LocalLaya()), vision_enabled=False,
    )
    try:
        scope = controller.route.now
        controller.memory.checkpoint("before")
        assert controller.add_operator_message("guide", "Try the west exit")
        assert controller.add_operator_message("remember", "The guard mentioned Pagota")
        controller.toggle_lean_context()
        context = controller.strategy.context(_state())
        assert context["context_mode"] == "lean"
        assert context["operator_guidance"]["text"] == "Try the west exit"
        assert context["operator_notes"][0]["text"] == "The guard mentioned Pagota"
        assert controller.memory.restore("before")
        assert controller.memory.experience.active_guide(scope)["text"] == "Try the west exit"
        controller.recovery = {"attempts": 2}
        controller.shopping = {"target": [4, 5]}
        controller.capture = {"phase": "menu"}
        from jpp.agent.gold97_battle import BattleAction
        controller.battle_executor.action = BattleAction(
            "ball", reason="Capture GRIMBY")
        controller.pending_frames = 30
        controller.replan()
        assert controller.recovery is None and controller.shopping is None
        assert controller.capture is None and controller.pending_frames == 0
        assert controller.battle_executor.action is None
        assert controller.live_snapshot()["decision"]["action"] == "Read current game state"
        assert controller.memory.experience.operator_messages()
        controller.memory.experience.retire_guides(scope + 1)
        assert controller.memory.experience.active_guide(scope) is None
    finally:
        controller.close()


def test_model_call_diagnostics_persist_without_full_prompt(tmp_path):
    path = tmp_path / "agent.sqlite"
    memory = Gold97Memory("run", path)
    live = LiveAgentState(memory)
    live.model_call(
        "laya", {"input_tokens": 42, "latency_ms": 18},
        {"state": {"goal": "Continue"},
         "context": {"budget": 100, "retained_tokens": 42,
                     "submitted_tokens": 80, "omitted_fields": ["memory"]}},
        confidence=.75,
    )
    assert live.snapshot()["model_calls"][-1]["retained_tokens"] == 42
    memory.close()
    memory = Gold97Memory("run", path)
    restored = LiveAgentState(memory).snapshot()["model_calls"][-1]
    assert restored["input_tokens"] == 42 and restored["confidence"] == .75
    assert "state" not in restored
    memory.close()


def test_luna_vision_keeps_exact_submitted_frame_in_memory(tmp_path):
    class Vision:
        def model_input(self, frame):
            return {"model": "test", "prompt": "Read", "image": {"width": 160, "height": 144}}

        def describe(self, frame):
            return {"mode": "menu", "screen_text": ["CONTINUE"],
                    "walkable_directions": [], "uncertainty": "",
                    "usage": {"input_tokens": 12, "output_tokens": 3, "latency_ms": 4}}

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(_LocalLaya()), vision=Vision(),
    )
    try:
        frame = np.arange(144 * 160 * 4, dtype=np.uint8).reshape((144, 160, 4))
        state = _state()
        assert controller._screen(state, frame) is None
        frame[:] = 0
        controller.vision_future.result(timeout=1)
        controller._screen(state, frame)
        vision = controller.live_snapshot()["vision"]
        assert vision["status"] == "completed"
        assert vision["result"]["screen_text"] == ["CONTINUE"]
        assert vision["model_input"]["prompt"] == "Read"
        assert np.any(vision["frame"] != 0)
    finally:
        controller.close()


def test_agent_panel_hides_zero_usage_and_visual_controls_are_not_click_targets():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        rendered = []
        original = ui.text

        def capture(value, *args, **kwargs):
            rendered.append(str(value))
            return original(value, *args, **kwargs)

        ui.text = capture
        ui._thoughts(
            {"laya": []}, Animation(),
            {"tactical_provider": "laya", "tactical_label": "Laya",
             "tactical_available": True, "control_mode": "ai",
             "active_input": "a", "input_source": "ai",
             "strategy": {"enabled": True},
             "model_usage": {"laya": {"calls": 0}, "luna": {"calls": 0}}},
        )
        assert "Laya playing" in rendered and "Luna on" in rendered
        assert not any("0 call" in value or "unavailable" in value.lower() for value in rendered)
        assert "toggle_jev" in ui.actions
        assert not {"up", "down", "left", "right", "a", "b", "start", "select"} & ui.actions.keys()
    finally:
        pygame.quit()
