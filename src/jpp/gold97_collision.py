"""Walkability from the active Gold 97 map blocks and ROM collision table."""

from dataclasses import dataclass


_MAP_WIDTH = 0xD19F
_MAP_HEIGHT = 0xD19E
_COLLISION_BANK = 0xD1DF
_COLLISION_ADDRESS = 0xD1E0
_BLOCKS = 0xC800
_WALL = {1, 7, 15, 18, 21, 26, 29, 39, 47, 98, 106, 255}
_WALL.update(range(128, 133))
_WALL.update(range(136, 141))
_WALL.update(range(144, 160))
_WATER = {32, 33, 34, 36, 37, 38, 40, 41, 42, 44, 45, 46}
_WATER.update(range(48, 64))
_WATER.update(range(192, 208))
_HOPS = {0xA0: "right", 0xA1: "left", 0xA2: "up", 0xA3: "down"}


@dataclass(frozen=True)
class Gold97CollisionMap:
    map_key: tuple[int, int]
    width: int
    height: int
    tiles: bytes

    @classmethod
    def from_emulator(cls, emulator, state):
        memory = emulator.memory
        width = memory[1, _MAP_WIDTH]
        height = memory[1, _MAP_HEIGHT]
        if (not width or not height or width * 2 != state.map_width
                or height * 2 != state.map_height):
            return None
        stride = width + 6
        bank = memory[1, _COLLISION_BANK]
        address = (memory[1, _COLLISION_ADDRESS]
                   | memory[1, _COLLISION_ADDRESS + 1] << 8)
        if not bank or not 0x4000 <= address < 0x8000:
            return None
        blocks = [memory[_BLOCKS + 3 * stride + 3 + row * stride + col]
                  for row in range(height) for col in range(width)]
        collisions = {}
        tiles = bytearray(width * height * 4)
        for y in range(height * 2):
            for x in range(width * 2):
                block = blocks[(y // 2) * width + x // 2]
                if block not in collisions:
                    offset = address + 4 * block
                    collisions[block] = tuple(memory[bank, offset + i] for i in range(4))
                tiles[y * width * 2 + x] = collisions[block][(y % 2) * 2 + x % 2]
        return cls((state.map_group, state.map_number), width * 2, height * 2,
                   bytes(tiles))

    def tile(self, point):
        x, y = point
        if not 0 <= x < self.width or not 0 <= y < self.height:
            return None
        return self.tiles[y * self.width + x]

    def allows(self, point, direction):
        tile = self.tile(point)
        if tile is None or tile in _WALL or tile in _WATER:
            return False
        if 0xA0 <= tile <= 0xA7:
            return _HOPS.get(tile) == direction
        return True

    def cost(self, point):
        return 8 if self.tile(point) in {0x10, 0x14, 0x18, 0x1C} else 1


class Gold97CollisionCache:
    """Re-read collision blocks while a newly entered map finishes loading."""

    def __init__(self, refresh_frames=16):
        self.refresh_frames = refresh_frames
        self.reset()

    def reset(self):
        self.map_key = None
        self.frames = 0
        self.terrain = None
        self.was_in_battle = False

    @property
    def ready(self):
        return self.frames > self.refresh_frames

    def update(self, emulator, state):
        map_key = (state.map_group, state.map_number)
        in_battle = getattr(state, "in_battle", False)
        if map_key != self.map_key or self.was_in_battle and not in_battle:
            self.map_key = map_key
            self.frames = 0
            self.terrain = None
        self.was_in_battle = in_battle
        self.frames += 1
        if (self.frames <= self.refresh_frames or self.terrain is None or
                not self._has_exit(state)):
            current = Gold97CollisionMap.from_emulator(emulator, state)
            if current is not None:
                self.terrain = current
        return self.terrain

    def _has_exit(self, state):
        if self.terrain is None or state.x is None or state.y is None:
            return False
        return any(self.terrain.allows((state.x + dx, state.y + dy), direction)
                   for direction, (dx, dy) in
                   (("up", (0, -1)), ("down", (0, 1)),
                    ("left", (-1, 0)), ("right", (1, 0))))
