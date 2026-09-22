"""NPC priorities and dialogue retention at the battle boundary."""
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.journey_guidance import rank_candidates
from jpp.agent.journey_knowledge import JourneyKnowledge
from jpp.agent.journey_targets import candidates, target_options
from jpp.gold97_collision import Gold97CollisionMap


def test_goal_gym_conversation_beats_departure():
    tasks = [{"id": "npc", "kind": "talk", "label": "Talk to an unvisited sprite"},
             {"id": "exit", "kind": "exit", "destination": "Pagota City"}]
    ranked = rank_candidates(tasks, "Defeat Falkner in Pagota Gym", current_area="Pagota Gym")
    assert ranked[0]["id"] == "npc"
    assert ranked[0]["journey_reward"] >= 100
    ranked = rank_candidates(tasks, "Visit Bill after beating Falkner", current_area="Pagota Gym")
    assert ranked[0]["id"] == "exit"


def test_new_conversation_beats_aimless_exit_but_not_known_goal():
    tasks = [{"id": "npc", "kind": "talk"},
             {"id": "exit", "kind": "exit", "destination": "Unknown area"}]
    assert rank_candidates(tasks, "Find a way onward")[0]["id"] == "npc"
    tasks[1].update(destination="Route 102", destination_key="09:01")
    assert rank_candidates(tasks, "Use Cut to progress through Route 102")[0]["id"] == "exit"


def test_talk_faces_sprite_and_completed_conversation_stays_excluded(tmp_path):
    memory = Gold97Memory("npc-policy", tmp_path / "memory.sqlite")
    try:
        obs = JourneyKnowledge(memory)
        state = NS(map_group=9, map_number=2, x=1, y=1, map_width=6,
                   map_height=6, area_name="Pagota Gym", in_battle=False, screen_lines=())
        entity = NS(key="object:1", pixel_x=32, pixel_y=16)
        obs.observe(state, (entity,), overworld=True, milestone=5)
        terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
        target = candidates(state, memory, terrain)[0]
        assert target_options(target, state, memory, terrain) == {
            "right": "Face the sprite", "a": "Talk to the sprite"}
        obs.interacted(target["id"])
        state.screen_lines = ("Train carefully before the next challenge.",)
        for _ in range(4):
            obs.observe(state, (), overworld=False, milestone=5, prompt_visible=True)
        obs.observe(state, (entity,), overworld=True, milestone=5)
        obs.observe(state, (entity,), overworld=True, milestone=6)
        assert all(t["kind"] != "talk" for t in candidates(state, memory, terrain))
        assert obs.data["npcs"][target["id"]]["pages"] == list(state.screen_lines)
    finally:
        memory.close()


@pytest.mark.parametrize("result, expected", [(0, "talked"), (1, "pending"), (None, "pending")])
def test_stable_leader_dialogue_survives_battle_start(tmp_path, result, expected):
    memory = Gold97Memory("gym-dialogue", tmp_path / "memory.sqlite")
    try:
        obs = JourneyKnowledge(memory)
        state = NS(map_group=9, map_number=2, x=1, y=1,
                   in_battle=False, screen_lines=())
        obs.observe(state, (NS(key="object:1", pixel_x=32, pixel_y=16),),
                    overworld=True, milestone=5)
        obs.interacted("09:02/object:1")
        state.screen_lines = ("I am FALKNER. Let me show you my power!",)
        for _ in range(4):
            obs.observe(state, (), overworld=False, milestone=5, prompt_visible=True)
        state.in_battle = True
        state.screen_lines = ("PIDGEY used GUST!",)
        for _ in range(3):
            obs.observe(state, (), overworld=False, milestone=5)
        assert obs.data["npcs"]["09:02/object:1"]["pages"] == [
            "I am FALKNER. Let me show you my power!"]
        assert len(obs.data["clues"]) == 1
        assert obs.data["stats"]["luna_on"]["conversation_battle"] == 1
        assert obs.pending is None
        state.in_battle = False
        state.battle_result = result
        obs.observe(state, (), overworld=False, milestone=5)
        assert obs.data["npcs"]["09:02/object:1"]["status"] == expected
    finally:
        memory.close()
