"""Cartridge-safe input timing and checkpoint input reset."""

_MOVES = {"up", "down", "left", "right"}
_BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
def release_restored_buttons(emulator):
    """A PyBoy state can contain a held D-pad button from its save frame."""
    for button in _BUTTONS:
        emulator.button_release(button)


def press_action(emulator, action, *, menu=False):
    if action in _MOVES and not menu:
        emulator.button_press(action)
    else:
        emulator.button(action, 4)


def hold_action(emulator, action):
    """Press a direction until its owner explicitly releases it."""
    if action not in _MOVES:
        raise ValueError(f"only movement buttons can be held: {action}")
    emulator.button_press(action)


def renew_movement(emulator, active, expected, *, overworld, in_battle,
                   pressed=False):
    """Keep native directional input down while the controller still owns it."""
    # Timed taps own their scheduled release. Releasing A on the next frame
    # truncates its four-frame pulse and can miss the game's input polling.
    if active not in _MOVES:
        return None
    walking = (active in _MOVES and active == expected and
               overworld and not in_battle)
    if active is not None and not walking and not pressed:
        emulator.button_release(active)
        return None
    return active
