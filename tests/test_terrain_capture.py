from types import SimpleNamespace
from collections import defaultdict

import numpy as np

from jpp.terrain_capture import (WorldCamera, overworld_ready, visible_background,
                                 visible_entities, visible_player, visible_prompt)


class _Memory(defaultdict):
    def __init__(self, sprite_updates):
        super().__init__(int, {0xC2CE: sprite_updates, 0xFF68: 0xC0})
        shades = (22, 10, 5, 0)
        self.palette_data = b"".join(
            (shade | shade << 5 | shade << 10).to_bytes(2, "little")
            for _ in range(8) for shade in shades
        )

    def __getitem__(self, key):
        if key == 0xFF69:
            return self.palette_data[super().__getitem__(0xFF68) & 0x3F]
        return super().__getitem__(key)


def _emulator(sprite_updates=1, window=(160, 144), white=False):
    memory = _Memory(sprite_updates)
    for index, (x, y) in enumerate(((60, 64), (60, 72), (68, 64), (68, 72))):
        memory[0xFE00 + index * 4] = y + 16
        memory[0xFE01 + index * 4] = x + 8
    frame = np.full((144, 160, 4), 255 if white else 180, dtype=np.uint8)
    return SimpleNamespace(memory=memory,
                           screen=SimpleNamespace(get_tilemap_position=lambda: ((0, 0), window),
                                                  ndarray=frame),
                           tilemap_background=SimpleNamespace(
                               tile_identifier=lambda x, y: 17,
                               map_offset=0x9800,
                               tile=lambda x, y: SimpleNamespace(
                                   ndarray=lambda: np.full((8, 8, 4), 90, dtype=np.uint8))))


def _state(battle=False):
    return SimpleNamespace(in_battle=battle, map_width=20, map_height=26, x=8, y=8)


def test_observed_viewport_decodes_background_instead_of_lagging_sprite_screen():
    emulator = _emulator()
    emulator.screen.ndarray[64:80, 60:76] = 0
    cells = visible_background(emulator, _state())
    assert len(cells) == 20 * 18
    terrain = bytes((176, 176, 176, 255)) * 64
    assert cells[0] == (8, 7, 17, terrain)
    assert any((x, y, rgba) == (15, 15, terrain)
               for x, y, _, rgba in cells)
    assert emulator.memory[0xFF68] == 0xC0
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


def test_boundary_loading_coordinate_is_not_an_observed_map_position():
    for x, y in ((255, 8), (20, 8), (8, 26), (-1, 8)):
        state = _state()
        state.x, state.y = x, y
        assert not overworld_ready(_emulator(), state)
        assert not visible_background(_emulator(), state)


def test_walk_input_can_resume_before_camera_alignment_but_not_during_text():
    emulator = _emulator()
    emulator.screen.get_tilemap_position = lambda: ((3, 0), (160, 144))
    assert not visible_background(emulator, _state())
    assert overworld_ready(emulator, _state())

    map_art = _state()
    map_art.screen_lines = ("",) * 14 + ("QQ bQ QQ",) + ("",) * 3
    assert overworld_ready(emulator, map_art)
    assert not visible_prompt(emulator, map_art)

    dialogue = _state()
    dialogue.screen_lines = ("",) * 14 + ("Please come in",) + ("",) * 3
    emulator.screen.ndarray[-40:, :, :3] = 255
    assert not overworld_ready(emulator, dialogue)
    assert visible_prompt(emulator, dialogue)
    assert not overworld_ready(_emulator(white=True), _state())


def test_fade_or_blank_transition_does_not_confirm_stale_text():
    emulator = _emulator(white=True)
    state = _state()
    state.screen_lines = ("",) * 14 + ("Old battle text",) + ("",) * 3
    assert not overworld_ready(emulator, state)
    assert not visible_prompt(emulator, state)


def test_map_loading_window_does_not_confirm_stale_text():
    emulator = _emulator(window=(0, 0))
    state = _state()
    state.screen_lines = ("",) * 14 + ("Old NPC text",) + ("",) * 3
    assert not visible_prompt(emulator, state)


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


def test_gold97_item_ball_object_is_tagged_without_pixel_guessing():
    emulator = _emulator()
    state = _state()
    state.map_group, state.map_number = 20, 2
    state.map_width, state.map_height = 52, 38
    state.mechanics_verified = True
    base = 0xD6FC + 16
    emulator.memory[1, base] = 1
    emulator.memory[1, base + 1] = 0x4E
    emulator.memory[1, base + 2] = state.y + 4
    emulator.memory[1, base + 3] = state.x + 5
    emulator.memory[1, base + 8] = 1
    entities = visible_entities(emulator, state)
    items = [entity for entity in entities if entity.kind == "item"]
    assert len(items) == 1
    assert (items[0].pixel_x, items[0].pixel_y) == ((state.x + 1) * 16, state.y * 16)


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


def test_camera_waits_for_new_map_to_settle_before_terrain_capture():
    emulator = _emulator()
    camera = WorldCamera()
    state = _state()
    state.map_group, state.map_number = 9, 2
    for expected in (1, 2, 3):
        assert camera.position(emulator, state) is not None
        assert camera.map_frames == expected
    state.map_number = 3
    assert camera.position(emulator, state) is not None
    assert camera.map_frames == 1
    assert camera.position(emulator, _state(battle=True)) is None
    assert camera.map_frames == 0


def test_background_uses_the_same_world_origin_as_the_sprite_layer():
    emulator = _emulator()
    emulator.screen.get_tilemap_position = lambda: ((8, 0), (160, 144))
    cells = visible_background(emulator, _state(), world_origin=(72, 56))
    assert cells[0][:2] == (9, 7)


def test_background_decodes_vram_bank_flip_and_palette_without_screen_pixels():
    emulator = _emulator()
    emulator.memory[1, 0x9800] = 0x29  # bank 1, horizontal flip, palette 1
    emulator.memory[1, 0x8000 + 17 * 16] = 0x80
    cells = visible_background(emulator, _state())
    tile = cells[0][3]
    assert tile[:4] == bytes((176, 176, 176, 255))
    assert tile[28:32] == bytes((80, 80, 80, 255))


def test_uniform_transition_palette_is_not_saved_as_terrain():
    emulator = _emulator()
    emulator.memory.palette_data = bytes(64)
    assert visible_background(emulator, _state()) == ()
