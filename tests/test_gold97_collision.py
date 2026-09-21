from types import SimpleNamespace

from jpp.gold97_collision import Gold97CollisionCache, Gold97CollisionMap


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


def test_collision_cache_refreshes_a_stale_grid_after_a_map_warp():
    memory = Memory()
    memory[1, 0xD19F] = 2
    memory[1, 0xD19E] = 1
    memory[1, 0xD1DF] = 55
    memory[1, 0xD1E0] = 0x00
    memory[1, 0xD1E1] = 0x50
    for col in range(2):
        memory[0xC800 + 3 * 8 + 3 + col] = 1
    for index in range(4):
        memory[55, 0x5004 + index] = 7  # previous map's collision table
        memory[55, 0x5104 + index] = 0  # new map's open ground
    state = SimpleNamespace(map_group=9, map_number=2, map_width=4,
                            map_height=2, x=1, y=0)
    emulator = SimpleNamespace(memory=memory)
    cache = Gold97CollisionCache(refresh_frames=2)

    assert not cache.update(emulator, state).allows((2, 0), "right")
    assert not cache.ready
    assert not cache.update(emulator, state).allows((2, 0), "right")
    assert not cache.ready
    memory[1, 0xD1E0] = 0x00
    memory[1, 0xD1E1] = 0x51
    assert cache.update(emulator, state).allows((2, 0), "right")
    assert cache.ready

    state.in_battle = True
    cache.update(emulator, state)
    state.in_battle = False
    assert cache.update(emulator, state).allows((2, 0), "right")
    assert not cache.ready
