from types import SimpleNamespace

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_items import is_item_entity, item_action
from jpp.route_progress import RouteProgress


def _state(x=43, y=31):
    return SimpleNamespace(
        map_group=20, map_number=2, x=x, y=y, map_width=52, map_height=38,
        area_name="Route 101", in_battle=False, party=(), badge_ids=(),
        pokedex_caught_ids=(), battle=SimpleNamespace(kind="none", opponent=None),
    )


def _item(x, y):
    return SimpleNamespace(pixel_x=x * 16, pixel_y=y * 16, kind="item", key=f"item:{x}:{y}")


def test_item_entities_are_explicit_and_do_not_guess_from_unknown_sprites():
    assert is_item_entity(_item(4, 4))
    assert not is_item_entity(SimpleNamespace(kind="unknown", key="npc:v2:4:4"))


def test_item_route_targets_a_neighbor_instead_of_walking_onto_the_item(tmp_path):
    class Memory:
        def map(self, key):
            return {"visited": [], "edges": [], "blocked": []}

    state = _state()
    assert item_action(Memory(), state, (_item(46, 31),)) == "right"


def test_visible_item_preempts_a_story_waypoint_and_is_not_retried(tmp_path):
    controller = Gold97Controller("run", database=tmp_path / "agent.sqlite")
    try:
        controller.route = RouteProgress(completed={1, 2})
        state = _state()
        entity = _item(44, 31)

        assert controller.step(state, entities=(entity,), overworld=True) == "a"
        assert controller.opening_goal == "Collect the nearby item before continuing"

        controller.cooldown = 0
        assert controller.step(state, entities=(entity,), overworld=True) != "a"
    finally:
        controller.close()
