from types import SimpleNamespace
from collections import defaultdict

import numpy as np

from jpp.terrain_capture import visible_background, visible_entities, visible_player


def _emulator(sprite_updates=1, window=(160, 144), white=False):
    memory = defaultdict(int, {0xC2CE: sprite_updates})
    for index, (x, y) in enumerate(((60, 64), (60, 72), (68, 64), (68, 72))):
        memory[0xFE00 + index * 4] = y + 16
        memory[0xFE01 + index * 4] = x + 8
    frame = np.full((144, 160, 4), 255 if white else 180, dtype=np.uint8)
    return SimpleNamespace(memory=memory,
                           screen=SimpleNamespace(get_tilemap_position=lambda: ((0, 0), window),
                                                  ndarray=frame),
                           tilemap_background=SimpleNamespace(tile_identifier=lambda x, y: 17))


def _state(battle=False):
    return SimpleNamespace(in_battle=battle, map_width=20, map_height=26, x=8, y=8)


def test_observed_viewport_uses_background_tiles_not_sprite_screen():
    cells = visible_background(_emulator(), _state())
    assert 300 < len(cells) < 20 * 18  # the player is excluded
    assert cells[0] == (8, 7, 17, bytes([180] * 256))
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
    base = 0xFE00 + 4 * 4
    emulator.memory[base] = 80  # screen y 64
    emulator.memory[base + 1] = 88  # screen x 80
    emulator.memory[base + 2] = 1
    for row in range(8):
        emulator.memory[0x8010 + row * 2] = 0xFF
    cells = visible_background(emulator, _state())
    assert not any(x == 18 and y == 15 for x, y, _, _ in cells)
    entities = visible_entities(emulator, _state())
    assert len(entities) == 1
    assert entities[0][:2] == (144, 120)
    assert entities[0][2][3] == 180  # screen alpha in the synthetic frame


def test_player_sprite_uses_current_oam_pixels_only_on_overworld():
    emulator = _emulator()
    for index in range(4):
        emulator.memory[0xFE02 + index * 4] = 1
    for row in range(8):
        emulator.memory[0x8010 + row * 2] = 0xFF
    pixels = visible_player(emulator, _state())
    assert pixels is not None
    assert np.frombuffer(pixels, dtype=np.uint8).reshape(16, 16, 4)[:, :, 3].min() == 180
    assert visible_player(emulator, _state(battle=True)) is None
    assert visible_player(_emulator(sprite_updates=0), _state()) is None
