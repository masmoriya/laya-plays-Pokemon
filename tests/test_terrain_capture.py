from types import SimpleNamespace
from collections import defaultdict

import numpy as np

from jpp.terrain_capture import WorldCamera, visible_background, visible_entities, visible_player


def _emulator(sprite_updates=1, window=(160, 144), white=False):
    memory = defaultdict(int, {0xC2CE: sprite_updates})
    for index, (x, y) in enumerate(((60, 64), (60, 72), (68, 64), (68, 72))):
        memory[0xFE00 + index * 4] = y + 16
        memory[0xFE01 + index * 4] = x + 8
    frame = np.full((144, 160, 4), 255 if white else 180, dtype=np.uint8)
    return SimpleNamespace(memory=memory,
                           screen=SimpleNamespace(get_tilemap_position=lambda: ((0, 0), window),
                                                  ndarray=frame),
                           tilemap_background=SimpleNamespace(
                               tile_identifier=lambda x, y: 17,
                               tile=lambda x, y: SimpleNamespace(
                                   ndarray=lambda: np.full((8, 8, 4), 90, dtype=np.uint8))))


def _state(battle=False):
    return SimpleNamespace(in_battle=battle, map_width=20, map_height=26, x=8, y=8)


def test_observed_viewport_uses_background_tiles_not_sprite_screen():
    emulator = _emulator()
    emulator.screen.ndarray[64:80, 60:76] = 0
    cells = visible_background(emulator, _state())
    assert len(cells) == 20 * 18
    assert cells[0] == (8, 7, 17, bytes([180] * 256))
    assert any((x, y, rgba) == (15, 15, bytes([180] * 256))
               for x, y, _, rgba in cells)
    moved = _state()
    moved.x = 9
    assert visible_background(_emulator(), moved)[0][:2] == (10, 7)


def test_menu_battle_and_window_frames_never_enter_map():
    assert not visible_background(_emulator(sprite_updates=0), _state())
    assert not visible_background(_emulator(), _state(battle=True))
    assert not visible_background(_emulator(window=(0, 0)), _state())
    assert not visible_background(_emulator(white=True), _state())
    textbox = _emulator()
    textbox.screen.ndarray[-40:, :, :3] = 255
    assert not visible_background(textbox, _state())


def test_live_npc_sprite_layer_is_separate_from_persisted_terrain():
    emulator = _emulator()
    for index, (x, y) in enumerate(((80, 64), (88, 64), (80, 72), (88, 72)), start=4):
        base = 0xFE00 + index * 4
        emulator.memory[base] = y + 16
        emulator.memory[base + 1] = x + 8
        emulator.memory[base + 2] = 1
    for row in range(8):
        emulator.memory[0x8010 + row * 2] = 0xFF
    cells = visible_background(emulator, _state())
    assert any(x == 18 and y == 15 for x, y, _, _ in cells)
    entities = visible_entities(emulator, _state())
    assert len(entities) == 1
    assert entities[0].key == "oam:4"
    assert entities[0].map_key == "00:00"
    assert (entities[0].pixel_x, entities[0].pixel_y) == (144, 120)
    assert len(entities[0].rgba) == 1024
    assert entities[0].rgba[3] == 180  # screen alpha in the synthetic frame


def test_player_sprite_uses_current_oam_pixels_only_on_overworld():
    emulator = _emulator()
    for index in range(4):
        emulator.memory[0xFE02 + index * 4] = 1
    for row in range(8):
        emulator.memory[0x8010 + row * 2] = 0xFF
    pixels = visible_player(emulator, _state())
    assert pixels is not None
    assert pixels.key == "player"
    assert (pixels.pixel_x, pixels.pixel_y) == (124, 120)
    assert np.frombuffer(pixels.rgba, dtype=np.uint8).reshape(16, 16, 4)[:, :, 3].min() == 180
    assert visible_player(emulator, _state(battle=True)) is None
    assert visible_player(_emulator(sprite_updates=0), _state()) is None


def test_partially_visible_npc_is_kept_as_transparent_sprite():
    emulator = _emulator()
    for index, x in ((14, 64), (15, 72)):
        base = 0xFE00 + index * 4
        emulator.memory[base] = 20
        emulator.memory[base + 1] = x + 8
        emulator.memory[base + 2] = 1
    for row in range(8):
        emulator.memory[0x8010 + row * 2] = 0xFF
    entities = visible_entities(emulator, _state())
    assert len(entities) == 1
    assert entities[0].key == "oam:12"
    alpha = np.frombuffer(entities[0].rgba, dtype=np.uint8).reshape(16, 16, 4)[:, :, 3]
    assert alpha[:8].any()
    assert not alpha[8:].any()


def test_npc_map_position_stays_fixed_during_subtile_camera_scroll():
    emulator = _emulator()
    for index, (x, y) in enumerate(((80, 64), (88, 64), (80, 72), (88, 72)), start=4):
        emulator.memory[0xFE00 + index * 4] = y + 16
        emulator.memory[0xFE01 + index * 4] = x + 8
        emulator.memory[0xFE02 + index * 4] = 1
    for row in range(8):
        emulator.memory[0x8010 + row * 2] = 0xFF
    camera = WorldCamera()
    first = visible_entities(emulator, _state(), world_origin=camera.position(emulator, _state()))

    emulator.screen.get_tilemap_position = lambda: ((6, 0), (160, 144))
    for index in range(4):
        emulator.memory[0xFE01 + index * 4] += 8
    for index in range(4, 8):
        emulator.memory[0xFE01 + index * 4] -= 6
    second = visible_entities(emulator, _state(), world_origin=camera.position(emulator, _state()))

    assert first[0].pixel_x == second[0].pixel_x


def test_background_uses_the_same_world_origin_as_the_sprite_layer():
    emulator = _emulator()
    emulator.screen.get_tilemap_position = lambda: ((8, 0), (160, 144))
    cells = visible_background(emulator, _state(), world_origin=(72, 56))
    assert cells[0][:2] == (9, 7)
