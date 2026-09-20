from types import SimpleNamespace

from jpp.gold97_catalog import map_details
from jpp.journey import Journey
from jpp.route_progress import BRASS_TOWER_ROOF, MAIN, OPTIONAL, RouteProgress
from jpp.terrain_capture import OverworldSprite


def _state(*, battle=False, area="Silent Town"):
    return SimpleNamespace(map_group=21, map_number=3, map_width=20, map_height=26,
                           x=8, y=8, in_battle=battle, area_name=area,
                           party=(), badge_ids=())


def _tile(x=1, y=1):
    return (x, y, 42, bytes([127] * 256))


def _entity(x=32, y=40, key="npc:v2:32:40"):
    return OverworldSprite(key, "15:03", x, y, bytes([127] * 1024))


def test_route_contains_main_and_optional_stages_without_guessing_bosses():
    assert len(MAIN) == 127
    assert len(OPTIONAL) >= 40
    route = RouteProgress()
    route.observe(_state(area="Westport City"))
    assert 9 in route.completed  # arrival proven
    assert 10 not in route.completed  # Bugsy not proven
    route.observe(SimpleNamespace(area_name="Somewhere", badge_ids=tuple(range(8))))
    assert 66 not in route.completed  # eight badges do not prove Red was defeated
    assert route.now == 1
    assert route.confirm() == 1
    assert route.correct() == 1
    assert route.now == 1


def test_pagota_arrival_advances_journey_without_confirmation_and_persists(tmp_path):
    journey = Journey("run", tmp_path / "run.sqlite")
    journey.route.completed.update({1, 2})
    journey.save_route()
    state = _state(area=map_details(9, 2)[0])
    state.map_group, state.map_number = 9, 2
    assert state.area_name == "Pagota City"

    journey.observe_route(state)
    assert journey.route.now == 4
    assert 3 in journey.route.completed
    assert journey.route.manual_history == []
    journey.observe_route(state)
    assert journey.route.completed == {1, 2, 3}
    journey.close()

    resumed = Journey("run", tmp_path / "run.sqlite")
    assert resumed.route.now == 4
    resumed.close()


def test_route_101_with_starter_repairs_opening_rival_progress():
    route = RouteProgress()
    state = _state(area="Route 101")
    state.party = (SimpleNamespace(species="FLAMBEAR"),)
    route.observe(state)
    assert route.now == 3


def test_pagota_checkpoint_with_starter_repairs_earlier_progress():
    route = RouteProgress()
    state = _state(area="Pagota City")
    state.party = (SimpleNamespace(species="FLAMBEAR"),)
    route.observe(state)
    assert route.now == 4


def test_brass_tower_floors_do_not_complete_climb_stage():
    route = RouteProgress(completed={1, 2, 3})
    for map_number in (1, 5):
        route.observe(SimpleNamespace(map_group=3, map_number=map_number,
                                      area_name=f"Brass Tower {map_number}F",
                                      badge_ids=()))
        assert route.now == 4
        assert 4 not in route.completed


def test_brass_tower_roof_completes_climb_stage():
    route = RouteProgress(completed={1, 2, 3})
    route.observe(SimpleNamespace(map_group=BRASS_TOWER_ROOF[0],
                                  map_number=BRASS_TOWER_ROOF[1],
                                  area_name="Brass Tower Roof", badge_ids=()))
    assert 4 in route.completed
    assert route.now == 5


def test_observations_persist_and_rewind_with_checkpoint_without_losing_archive(tmp_path):
    path = tmp_path / "run.sqlite"
    journey = Journey("run", path)
    assert journey.observe_tiles(_state(), [_tile()]) == 1
    assert journey.observe_tiles(_state(battle=True), [_tile(2, 2)]) == 0
    assert journey.observe_tiles(_state(), [_tile(2, 2)], overworld=False) == 0
    journey.route.confirm()
    journey.save_route()
    journey.record_checkpoint("first.state")
    state = _state()
    state.x = 9
    journey.observe_tiles(state, [_tile(2, 2)])
    journey.route.confirm()
    journey.save_route()
    journey.close()

    resumed = Journey("run", path)
    assert len(resumed.tiles["15:03"]) == 2
    assert resumed.restore_checkpoint("first.state")
    assert len(resumed.tiles["15:03"]) == 1
    assert resumed.route.now == 2
    count = resumed.db.execute("SELECT COUNT(*) FROM journey_snapshots").fetchone()[0]
    assert count == 2  # the future view is archived, not discarded
    resumed.close()


def test_invalid_or_unknown_map_samples_never_write(tmp_path):
    journey = Journey("run", tmp_path / "run.sqlite")
    state = _state()
    assert journey.observe_tiles(state, [(-1, 2, 1, bytes(256)),
                                         (1, 1, 1, b"bad")]) == 0
    assert journey.tiles["15:03"] == {}
    journey.close()


def test_entity_memories_persist_and_rewind_with_checkpoints(tmp_path):
    path = tmp_path / "run.sqlite"
    journey = Journey("run", path)
    assert journey.observe_entities(_state(), [_entity()]) == 1
    assert journey.observe_entities(_state(battle=True), [_entity(64, 72)]) == 0
    journey.record_checkpoint("first.state")
    assert journey.observe_entities(_state(), [_entity(64, 72)]) == 1
    journey.close()

    resumed = Journey("run", path)
    assert resumed.entities["15:03"]["npc:v2:32:40"][:2] == (64, 72)
    assert resumed.restore_checkpoint("first.state")
    assert resumed.entities["15:03"]["npc:v2:32:40"][:2] == (32, 40)
    resumed.close()


def test_old_offset_ghosts_do_not_survive_reload(tmp_path):
    path = tmp_path / "run.sqlite"
    journey = Journey("run", path)
    journey.observe_entities(_state(), [_entity(key="npc:32:40")])
    journey.close()

    resumed = Journey("run", path)
    assert resumed.entities == {}
    current = resumed.track_entities(_state(), [_entity(key="oam:4")])
    assert current[0].key.startswith("npc:v2:")
    assert len(resumed.entities["15:03"]) == 1
    resumed.close()


def test_npc_identity_survives_oam_reordering_and_partial_frames(tmp_path):
    journey = Journey("run", tmp_path / "run.sqlite")
    first = _entity(80, 64, key="oam:8")
    tracked = journey.track_entities(_state(), [first])
    assert tracked[0].key.startswith("npc:v2:")
    partial = OverworldSprite("oam:12", "15:03", 80, 64, bytes(1024), parts=2)
    tracked_again = journey.track_entities(_state(), [partial])
    assert tracked_again[0].key == tracked[0].key
    assert tracked_again[0].rgba == first.rgba
    assert len(journey.entities["15:03"]) == 1
    journey.close()


def test_area_changes_keep_independent_observed_tiles_across_reload(tmp_path):
    database = tmp_path / "journey.sqlite"
    journey = Journey("run", database)
    first = _state()
    second = _state(area="Oak's Lab")
    second.map_number = 4
    assert journey.observe_tiles(first, [_tile(1, 1)]) == 1
    assert journey.observe_tiles(second, [_tile(2, 2)]) == 1
    journey.close()
    restored = Journey("run", database)
    assert set(restored.tiles) == {"15:03", "15:04"}
    assert (1, 1) in restored.tiles["15:03"]
    assert (2, 2) in restored.tiles["15:04"]
    restored.close()


def test_legacy_skewed_map_is_archived_without_erasing_route(tmp_path):
    database = tmp_path / "journey.sqlite"
    first = Journey("run", database)
    first.route.confirm()
    first.save_route()
    first.observe_tiles(_state(), [_tile()])
    first.db.execute("DELETE FROM journey_meta WHERE run_id=?", ("run",))
    first.db.commit()
    first.close()

    upgraded = Journey("run", database)
    assert upgraded.tiles == {}
    assert upgraded.route.now == 2
    row = upgraded.db.execute(
        "SELECT payload FROM journey_snapshots WHERE path LIKE '%legacy-map'"
    ).fetchone()
    assert row and '"map_version": 1' in row[0]
    upgraded.close()


def test_old_screen_pixel_map_is_archived_before_clean_recapture(tmp_path):
    database = tmp_path / "journey.sqlite"
    first = Journey("run", database)
    first.observe_tiles(_state(), [_tile()])
    first.observe_entities(_state(), [_entity()])
    first.db.execute("UPDATE journey_meta SET map_version=2 WHERE run_id=?", ("run",))
    first.db.commit()
    first.close()

    upgraded = Journey("run", database)
    assert upgraded.tiles == {}
    assert upgraded.entities == {}
    archive = upgraded.db.execute(
        "SELECT path,payload FROM journey_snapshots WHERE path LIKE '%legacy-map'"
    ).fetchone()
    assert archive and '"map_version": 2' in archive[1]
    assert upgraded.restore_checkpoint(archive[0])
    assert upgraded.tiles == {}  # old pixel maps cannot reintroduce corrupt cells
    assert upgraded.entities == {}
    upgraded.close()
