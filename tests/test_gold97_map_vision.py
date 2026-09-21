"""Map-vision assistance must remain bounded to movement, never A."""

import json
from threading import Event
from types import SimpleNamespace

import numpy as np

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_vision import LunaScreenReader
from jpp.agent.policy_adapter import ProviderPolicy
from jpp.gold97_collision import Gold97CollisionMap


def _state():
    return SimpleNamespace(
        map_group=23, map_number=10, x=3, y=5,
        map_width=10, map_height=10, area_name="Test Map",
        in_battle=False, party=(), badge_ids=(), pokedex_caught_ids=(),
        battle=SimpleNamespace(kind="none", opponent=None),
    )


def _blocked_terrain():
    return Gold97CollisionMap((23, 10), 10, 10, bytes([7] * 100))


class _LocalLaya:
    usage_provider = "laya"

    def decide_tactical(self, state, options):
        assert "a" not in options
        return {"action": next(iter(options))}


def test_collision_disagreement_probes_a_direction_without_luna(tmp_path):
    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(_LocalLaya()), vision_enabled=False,
    )
    try:
        state = _state()
        assert controller.step(state, overworld=True, terrain=_blocked_terrain()) is None
        controller.decision_future.result(timeout=1)
        assert controller.step(state, overworld=True,
                               terrain=_blocked_terrain()) in {
            "up", "down", "left", "right"
        }
    finally:
        controller.close()


def test_luna_map_guidance_prioritizes_visible_open_ground(tmp_path):
    class Vision:
        def describe(self, frame):
            raise AssertionError("cached map observation should be reused")

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(_LocalLaya()), vision=Vision(),
    )
    try:
        state = _state()
        controller.vision_key = (23, 10, 3, 5, "none", None)
        controller.screen_note = {
            "mode": "overworld", "screen_text": [],
            "walkable_directions": ["right"], "uncertainty": "",
        }
        frame = np.zeros((144, 160, 4), dtype=np.uint8)
        assert controller.step(state, frame=frame, overworld=True,
                               terrain=_blocked_terrain()) is None
        controller.decision_future.result(timeout=1)
        assert controller.step(state, frame=frame, overworld=True,
                               terrain=_blocked_terrain()) == "right"
    finally:
        controller.close()


def test_movement_continues_while_luna_reads_the_map(tmp_path):
    release_vision = Event()

    class SlowVision:
        def describe(self, frame):
            release_vision.wait(timeout=1)
            return {"mode": "overworld", "screen_text": [],
                    "walkable_directions": ["right"], "uncertainty": ""}

    controller = Gold97Controller(
        "run", database=tmp_path / "agent.sqlite",
        policy=ProviderPolicy(_LocalLaya()), vision=SlowVision(),
    )
    try:
        state = _state()
        frame = np.zeros((144, 160, 4), dtype=np.uint8)
        controller.stalls = 2
        assert controller.step(state, frame=frame, overworld=True,
                               terrain=_blocked_terrain()) is None
        controller.decision_future.result(timeout=1)
        assert controller.vision_future is not None
        assert controller.step(state, frame=frame, overworld=True,
                               terrain=_blocked_terrain()) in {
            "up", "down", "left", "right"
        }
    finally:
        release_vision.set()
        controller.close()


def test_luna_screen_reader_returns_map_directions(monkeypatch):
    payload = {"mode": "overworld", "screen_text": [],
               "walkable_directions": ["down", "right"], "uncertainty": ""}
    output = json.dumps({"type": "turn.completed",
                         "final_response": json.dumps(payload)}) + "\n"
    calls = []
    monkeypatch.setattr(
        "jpp.agent.gold97_vision.subprocess.run",
        lambda *args, **kwargs: (
            calls.append(kwargs) or
            SimpleNamespace(returncode=0, stdout=output, stderr="")
        ),
    )
    reader = LunaScreenReader()
    frame = np.zeros((144, 160, 4), dtype=np.uint8)
    note = reader.describe(frame)
    assert note["walkable_directions"] == ["down", "right"]
    assert calls[0]["input"] == reader.model_input(frame)["prompt"]
    assert reader.model_input(frame)["image"] == {
        "width": 160, "height": 144, "source": "Game Boy frame"
    }
