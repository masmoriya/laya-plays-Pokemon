"""The only test that needs a ROM. Local, never CI.

    POKEMON_ROM=/path/to/red.gb uv run pytest tests/test_smoke_rom.py -q

A synthetic RAM fixture cannot catch a wrong address, only a wrong reading of the right
one. This is the test that catches a wrong address: it boots the real game and asserts the
decoded values land in the ranges the game guarantees.
"""

import os

import pytest

from jpp import symbols as S
from jpp.decode import decode
from jpp.loop import Driver

ROM = os.environ.get("POKEMON_ROM")
pytestmark = pytest.mark.skipif(not ROM, reason="set POKEMON_ROM to run the ROM smoke test")


@pytest.fixture
def emulator():
    from pyboy import PyBoy

    emu = PyBoy(ROM, window="null")
    emu.set_emulation_speed(0)
    yield emu
    emu.stop(save=False)


def test_the_decoder_reads_a_real_boot(emulator):
    driver = Driver(emulator)
    for _ in range(75):  # ~600 frames
        state = driver.tick()
    assert state.map_id in S.MAP_NAMES or 0 <= state.map_id <= 0xF7
    assert 0 <= state.x < 64 and 0 <= state.y < 64
    assert len(state.party) <= 6
    assert state.battle.kind == "none"
    assert len(state.events) == S.EVENT_FLAGS_LEN
    assert state.money < 1_000_000


def test_the_cartridge_is_the_one_we_have_addresses_for(emulator):
    assert emulator.cartridge_title in ("POKEMON RED", "POKEMON BLUE")
