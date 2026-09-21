"""Stable active object identities from the verified overworld object structs."""


def active_objects(mem, width, height):
    result = []
    for slot in range(1, 13):
        base = 0xD4D6 + slot * 40
        sprite, index = mem[base], mem[base + 1]
        x, y = mem[base + 16] - 4, mem[base + 17] - 4
        if sprite and 1 <= index <= 15 and 0 <= x < width and 0 <= y < height:
            result.append((f'object:{index}', x, y))
    return tuple(result)
