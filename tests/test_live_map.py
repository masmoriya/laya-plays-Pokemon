"""Display contract checks, independent of autonomous routing."""
from types import SimpleNamespace

import pygame
import pytest

from jpp.gold97_collision import Gold97CollisionMap
from jpp.live_map_grid import cell_kind
from jpp.live_map_state import LiveMapState
from jpp.live_ui import LiveUI, SIZE
from jpp.live_ui_colors import BG, GOOD, MUTED, WARN
from jpp.terrain_capture import OverworldSprite


def state(**values):
    return SimpleNamespace(**dict(dict(map_group=20, map_number=4, map_width=4,
                                      map_height=3, x=0, y=0, in_battle=False,
                                      area_name="Test", locality=""), **values))


def terrain(tiles=bytes(12), key=(20, 4)):
    return Gold97CollisionMap(key, 4, 3, tiles)


def update(model, st=None, grid=None, **kwargs):
    model.update(st or state(), grid or terrain(),
                 **dict(dict(ready=True, overworld=True), **kwargs))


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    yield LiveUI(pygame.display.set_mode(SIZE))
    pygame.quit()


def test_cells_match_movement_rules():
    grid = terrain(bytes([0, 7, 32, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0, 0, 0, 0]))
    assert cell_kind(grid, (0, 0)) == ("walk", ("up", "down", "left", "right"))
    assert cell_kind(grid, (1, 0)) == ("blocked", ())
    assert cell_kind(grid, (2, 0)) == ("blocked", ())
    for point, direction in (((3, 0), "right"), ((0, 1), "left"),
                             ((1, 1), "up"), ((2, 1), "down")):
        assert cell_kind(grid, point) == ("ledge", (direction,))
    assert cell_kind(grid, (3, 1)) == ("blocked", ())
    assert cell_kind(grid, (-1, 0)) == ("unknown", ())


def test_menu_freezes_all_overlays_and_transition_clears():
    model = LiveMapState()
    update(model, destination=((20, 4), (3, 2)))
    previous = model.snapshot
    update(model, state(x=2), overworld=False)
    assert model.snapshot is previous
    update(model, state(map_number=5), overworld=False)
    assert model.snapshot is None
    update(model, ready=False)
    assert model.status == "Updating map"
    update(model)
    assert model.snapshot.position == (0, 0)
    update(model, state(in_battle=True))
    assert model.snapshot is None
    update(model, ready=False)
    assert model.snapshot is None
    update(model)
    model.reset()  # The restore/restart hooks must invalidate same-map snapshots too.
    update(model, overworld=False)
    assert model.snapshot is None


@pytest.mark.parametrize("st,grid", [
    (state(), terrain(key=(20, 5))), (state(map_width=5), terrain()),
    (state(x=4), terrain()), (state(y=None), terrain()),
    (state(), terrain(b"")),
])
def test_rejects_incoherent_snapshots(st, grid):
    model = LiveMapState()
    update(model)
    model.update(st, grid, ready=True, overworld=True)
    assert model.snapshot is None
    assert model.status == "Map unavailable"


@pytest.mark.parametrize("position", [(0, 0), (3, 0), (0, 2), (3, 2)])
def test_player_uses_current_coordinates_in_both_views(ui, position):
    st = state(x=position[0], y=position[1])
    update(ui.map_state, st)
    ui.player_marker = OverworldSprite("old", "14:04", 999, 999, bytes(1024))
    view = pygame.Rect(0, 0, 400, 300)
    center = (position[0] * 100 + 50, position[1] * 100 + 50)
    for artwork in (False, True):
        ui.canvas.fill(BG)
        if artwork:
            ui.panels.map_panel._area(st, SimpleNamespace(tiles={}), view)
        else:
            ui.panels.map_panel.grid.draw(ui.map_state.snapshot, view)
        assert ui.canvas.get_at(center)[:3] == GOOD


def test_goal_entities_clipping_and_cache(ui):
    entity = OverworldSprite("npc", "14:04", 16, 16, bytes(1024))
    update(ui.map_state, entities=(entity,), destination=((20, 4), (3, 2)))
    grid = ui.panels.map_panel.grid
    view = pygame.Rect(10, 10, 400, 300)
    grid.draw(ui.map_state.snapshot, view)
    cached = grid.surface
    assert ui.canvas.get_at((160, 160))[:3] == WARN
    with_goal = pygame.image.tobytes(ui.canvas.subsurface(view), "RGB")
    update(ui.map_state, state(x=1), destination=((20, 5), (3, 2)))
    grid.draw(ui.map_state.snapshot, view)
    assert grid.surface is cached
    assert ui.canvas.get_at((160, 160))[:3] == MUTED  # departed entity disappears
    assert pygame.image.tobytes(ui.canvas.subsurface(view), "RGB") != with_goal
    update(ui.map_state, grid=terrain(bytes([7]) + bytes(11)))
    grid.draw(ui.map_state.snapshot, view)
    assert grid.surface is not cached
    clip = pygame.Rect(12, 12, 5, 5)
    ui.canvas.set_clip(clip)
    grid.overlays(ui.map_state.snapshot, view)
    assert ui.canvas.get_clip() == clip


def test_modes_status_and_artwork_revision(ui):
    panel = ui.panels.map_panel
    labels = []
    ui.text = lambda text, *args, **kwargs: labels.append(text)
    journey = SimpleNamespace(tiles={}, tile_revision=0)
    panel.draw(state(), journey)
    assert ui.map_mode == "grid"
    assert "Map unavailable" in labels
    assert "map_grid" in ui.actions and "map_artwork" in ui.actions
    assert not ui.actions["map_grid"].colliderect(ui.actions["map_artwork"])
    update(ui.map_state)
    ui.map_mode = "artwork"
    panel.draw(state(), journey)
    assert "Explored imagery" in labels
    before = panel._terrain
    journey.tiles = {"14:04": {(0, 0): (1, bytes([100, 120, 140, 0]) * 64)}}
    journey.tile_revision += 1
    panel.draw(state(), journey)
    assert panel._terrain is not before
    assert panel._terrain.get_at((0, 0)) == (100, 120, 140, 255)


@pytest.mark.parametrize("width,height", [(4, 30), (30, 4), (1, 1)])
def test_full_map_fits_and_centers_at_different_aspect_ratios(ui, width, height):
    st = state(map_width=width, map_height=height)
    model = ui.map_state
    update(model, st, Gold97CollisionMap((20, 4), width, height, bytes(width * height)))
    view = pygame.Rect(20, 20, 394, 259)
    ui.panels.map_panel.grid.draw(model.snapshot, view)
    surface = ui.panels.map_panel.grid.surface
    assert surface.get_width() <= view.width
    assert surface.get_height() <= view.height
    assert view.contains(surface.get_rect(center=view.center))


def test_unsupported_map_data_is_unavailable():
    model = LiveMapState()
    model.update(SimpleNamespace(), None, ready=False, overworld=False)
    assert model.status == "Map unavailable"
