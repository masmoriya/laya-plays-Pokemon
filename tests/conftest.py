import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(FIXTURES))


def load_ram(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def battle_ram():
    return load_ram("ram_battle.bin")


@pytest.fixture
def overworld_ram():
    return load_ram("ram_overworld.bin")
