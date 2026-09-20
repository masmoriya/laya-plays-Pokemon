"""Requested Gold 97 character names in the cartridge's own text encoding."""

MOTHER_NAME = "Claudette"
RIVAL_NAME = "Astra"
MOTHER_ADDRESS = 0xD488
RIVAL_ADDRESS = 0xD493
NAME_LENGTH = 11
_END = 0x50


def _encode(name):
    if not name.isascii() or not name.isalpha() or len(name) >= NAME_LENGTH:
        raise ValueError("Gold 97 names must be 1-10 ASCII letters")
    return bytes((0x80 + ord(char) - ord("A") if char.isupper()
                  else 0xA0 + ord(char) - ord("a")) for char in name)


def _read(memory, address):
    return bytes(memory[1, address + offset] for offset in range(NAME_LENGTH)).split(
        bytes((_END,)), 1
    )[0]


def apply_requested_names(emulator):
    """Repair only the known auto-A/default names; leave custom names alone."""
    changes = []
    for address, requested, mistaken in (
        (MOTHER_ADDRESS, MOTHER_NAME, (_encode("AAAAAAA"), _encode("MOMMY"))),
        (RIVAL_ADDRESS, RIVAL_NAME, (_encode("AAAAAAA"), _encode("SILVER"))),
    ):
        if _read(emulator.memory, address) not in mistaken:
            continue
        encoded = _encode(requested) + bytes((_END,))
        for offset in range(NAME_LENGTH):
            emulator.memory[1, address + offset] = (
                encoded[offset] if offset < len(encoded) else _END
            )
        changes.append(requested)
    return tuple(changes)
