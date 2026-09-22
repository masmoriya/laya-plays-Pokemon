import pytest

from jpp.agent.gold97_input import hold_action, press_action, release_restored_buttons


def test_checkpoint_load_releases_latched_inputs():
    class Emulator:
        def __init__(self):
            self.released = []

        def button_release(self, button):
            self.released.append(button)

    emulator = Emulator()
    release_restored_buttons(emulator)
    assert emulator.released == ["up", "down", "left", "right",
                                 "a", "b", "start", "select"]


def test_walk_press_spans_one_tile_and_menu_press_is_bounded():
    class Emulator:
        def __init__(self):
            self.pressed = []

        def button_press(self, button):
            self.pressed.append((button, "held"))

        def button(self, button, frames):
            self.pressed.append((button, frames))

    emulator = Emulator()
    press_action(emulator, "left")
    press_action(emulator, "a")
    press_action(emulator, "down", menu=True)
    assert emulator.pressed == [("left", "held"), ("a", 4), ("down", 4)]


def test_hold_action_uses_native_button_press():
    class Emulator:
        def __init__(self):
            self.pressed = []

        def button_press(self, button):
            self.pressed.append(button)

    emulator = Emulator()
    hold_action(emulator, "right")
    hold_action(emulator, "up")

    assert emulator.pressed == ["right", "up"]


def test_hold_action_rejects_a():
    class Emulator:
        def button_press(self, button):
            raise AssertionError("A must not be renewed")

    with pytest.raises(ValueError, match="only movement"):
        hold_action(Emulator(), "a")


def test_a_tap_keeps_its_scheduled_release_between_frames():
    from jpp.agent.gold97_input import renew_movement

    class Emulator:
        def __init__(self):
            self.events = []

        def button(self, button, frames):
            self.events.append((button, frames))

        def button_release(self, button):
            self.events.append((button, 'released early'))

    emulator = Emulator()
    press_action(emulator, 'a')
    active = renew_movement(emulator, 'a', None, overworld=True,
                            in_battle=False, pressed=True)
    active = renew_movement(emulator, active, None, overworld=True,
                            in_battle=False)
    assert active is None
    assert emulator.events == [('a', 4)]


def test_menu_direction_keeps_its_scheduled_release_between_frames():
    from jpp.agent.gold97_input import renew_movement

    class Emulator:
        def __init__(self):
            self.events = []

        def button(self, button, frames):
            self.events.append((button, frames))

        def button_release(self, button):
            self.events.append((button, 'released early'))

    emulator = Emulator()
    press_action(emulator, 'right', menu=True)
    active = renew_movement(emulator, 'right', None, overworld=False,
                            in_battle=True, pressed=True)
    active = renew_movement(emulator, active, None, overworld=False,
                            in_battle=True)
    assert active is None
    assert emulator.events == [('right', 4)]
