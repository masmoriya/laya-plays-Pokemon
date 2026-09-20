from types import SimpleNamespace

from jpp.gold97_names import (
    MOTHER_ADDRESS, RIVAL_ADDRESS, _encode, apply_requested_names,
)


def _emulator(mother, rival):
    memory = {}
    for address, name in ((MOTHER_ADDRESS, mother), (RIVAL_ADDRESS, rival)):
        for offset, value in enumerate(_encode(name) + b"\x50"):
            memory[1, address + offset] = value
        for offset in range(len(name) + 1, 11):
            memory[1, address + offset] = 0x50
    return SimpleNamespace(memory=memory)


def test_requested_names_repair_auto_a_names_and_are_idempotent():
    emulator = _emulator("AAAAAAA", "AAAAAAA")
    assert apply_requested_names(emulator) == ("Claudette", "Astra")
    assert apply_requested_names(emulator) == ()
    assert bytes(emulator.memory[1, MOTHER_ADDRESS + i] for i in range(9)) == _encode("Claudette")
    assert bytes(emulator.memory[1, RIVAL_ADDRESS + i] for i in range(5)) == _encode("Astra")


def test_requested_names_preserve_custom_names():
    emulator = _emulator("Martha", "Nova")
    assert apply_requested_names(emulator) == ()
