from types import SimpleNamespace

from jpp.gold97_collision import Gold97CollisionMap


class Memory(dict):
    def __getitem__(self, key):
        return self.get(key, 0)


def test_collision_grid_uses_active_map_blocks_and_rom_table():
    memory = Memory()
    memory[1, 0xD19F] = 2
    memory[1, 0xD19E] = 1
    memory[1, 0xD1DF] = 55
    memory[1, 0xD1E0] = 0x00
    memory[1, 0xD1E1] = 0x50
    memory[0xC800 + 3 * 8 + 3] = 1
    memory[0xC800 + 3 * 8 + 4] = 2
    for index, value in enumerate((0, 0x18, 7, 0, 0, 0, 0, 0)):
        memory[55, 0x5004 + index] = value
    state = SimpleNamespace(map_group=3, map_number=50,
                            map_width=4, map_height=2)
    terrain = Gold97CollisionMap.from_emulator(SimpleNamespace(memory=memory), state)
    assert terrain.tile((1, 0)) == 0x18
    assert terrain.cost((1, 0)) == 8
    assert not terrain.allows((0, 1), "down")
    assert terrain.allows((2, 1), "down")
