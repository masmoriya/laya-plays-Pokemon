"""Read the actual color background tiles from Gold 97's VRAM."""


def _palettes(memory):
    """Read CGB background colors and restore the palette index register."""
    index = memory[0xFF68]
    try:
        data = []
        for offset in range(64):
            memory[0xFF68] = offset
            data.append(memory[0xFF69])
    finally:
        memory[0xFF68] = index
    colors = []
    for offset in range(0, 64, 2):
        value = data[offset] | data[offset + 1] << 8
        colors.append(((value & 31) << 3, ((value >> 5) & 31) << 3,
                       ((value >> 10) & 31) << 3, 255))
    return [colors[start:start + 4] for start in range(0, 32, 4)]


def _tile_rgba(memory, tile_id, attr, palettes):
    """Decode one 8x8 background tile, including bank, flips and CGB palette."""
    address = 0x8000 + tile_id * 16
    bank = 1 if attr & 0x08 else 0
    palette = palettes[attr & 0x07]
    pixels = bytearray(256)
    for y in range(8):
        source_y = 7 - y if attr & 0x40 else y
        low = memory[bank, address + source_y * 2]
        high = memory[bank, address + source_y * 2 + 1]
        for x in range(8):
            bit = x if attr & 0x20 else 7 - x
            shade = ((low >> bit) & 1) | (((high >> bit) & 1) << 1)
            pixels[(y * 8 + x) * 4:(y * 8 + x + 1) * 4] = bytes(palette[shade])
    return bytes(pixels)


def background_tiles(emulator, state, scroll_x, scroll_y, left, top):
    """Return screen-visible map tiles without the scrolling screen's pixel lag."""
    memory = emulator.memory
    tilemap = emulator.tilemap_background
    palettes = _palettes(memory)
    # Transition fades collapse each palette to one color; they are not terrain.
    if sum(len(set(palette)) > 1 for palette in palettes) < 2:
        return ()
    samples = []
    rendered = {}
    for row in range(18):
        for col in range(20):
            world_x, world_y = left + col, top + row
            if not (0 <= world_x < state.map_width * 2
                    and 0 <= world_y < state.map_height * 2):
                continue
            tile_x = (scroll_x // 8 + col) % 32
            tile_y = (scroll_y // 8 + row) % 32
            tile_id = tilemap.tile_identifier(tile_x, tile_y)
            attr = memory[1, tilemap.map_offset + tile_y * 32 + tile_x]
            key = (tile_id, attr)
            if key not in rendered:
                rendered[key] = _tile_rgba(memory, tile_id, attr, palettes)
            samples.append((world_x, world_y, tile_id, rendered[key]))
    return tuple(samples)
