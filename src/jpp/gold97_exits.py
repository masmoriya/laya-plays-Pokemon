"""Current-map exits from the verified cartridge header, not a story route."""
from .gold97_catalog import map_details


def map_exits(data, mem, width, height):
    if not width or not height:
        return ()
    exits = []
    bank = mem[0xD1A3]
    pointer = mem[0xD1A6] | mem[0xD1A7] << 8
    if bank and 0x4000 <= pointer < 0x8000:
        offset = bank * 0x4000 + pointer - 0x4000
        raw = data.rom[offset:offset + 260]
        count = raw[2] if len(raw) >= 3 else 255
        if count <= 32 and len(raw) >= 3 + 5 * count:
            for i in range(count):
                y, x, warp, group, number = raw[3 + i * 5:8 + i * 5]
                if 0 <= x < width and 0 <= y < height and map_details(group, number)[2]:
                    exits.append((x, y, '', group, number))
    # Connection flags: north/south/west/east = 8/4/2/1.
    flags = mem[0xD1A8]
    for mask, address, direction in ((8, 0xD1A9, 'up'), (4, 0xD1B5, 'down'),
                                     (2, 0xD1C1, 'left'), (1, 0xD1CD, 'right')):
        group, number = mem[address], mem[address + 1]
        if flags & mask and map_details(group, number)[2]:
            points = ([(x, 0 if direction == 'up' else height - 1) for x in range(width)]
                      if direction in {'up', 'down'} else
                      [(0 if direction == 'left' else width - 1, y) for y in range(height)])
            exits.extend((x, y, direction, group, number) for x, y in points)
    return tuple(exits)
