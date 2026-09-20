"""Cartridge-safe input timing and checkpoint input reset."""

_MOVES = {"up", "down", "left", "right"}
_BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
_WALK_FRAMES = 16


def release_restored_buttons(emulator):
    """A PyBoy state can contain a held D-pad button from its save frame."""
    for button in _BUTTONS:
        emulator.button_release(button)


def press_action(emulator, action, *, menu=False):
    emulator.button(action, _WALK_FRAMES if action in _MOVES and not menu else 4)
