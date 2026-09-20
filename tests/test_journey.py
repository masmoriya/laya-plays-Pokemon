from types import SimpleNamespace

from jpp.gold97_catalog import map_details
from jpp.journey import Journey
from jpp.route_progress import MAIN, OPTIONAL, RouteProgress


def _state(*, battle=False, area="Silent Town"):
    return SimpleNamespace(map_group=21, map_number=3, map_width=20, map_height=26,
                           x=8, y=8, in_battle=battle, area_name=area,
                           party=(), badge_ids=())


def _tile(x=1, y=1):
    return (x, y, 42, bytes([127] * 256))


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
