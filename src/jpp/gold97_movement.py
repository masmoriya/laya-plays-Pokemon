"""Validated in-flight player destination for the supported cartridge."""


def player_destination(memory, width, height):
    # Player object D4D6: next XY +10, current XY +12. Object coordinates
    # include the map's four-tile border; global player coordinates do not.
    destination = tuple(memory[0xD4E6 + i] - 4 for i in range(2))
    origin = tuple(memory[0xD4E8 + i] - 4 for i in range(2))
    if (abs(destination[0] - origin[0]) + abs(destination[1] - origin[1]) != 1
            or not all(0 <= x < width and 0 <= y < height
                       for x, y in (origin, destination))):
        return None
    return destination
