from jpp.agent.gold97_input import press_action, release_restored_buttons


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

        def button(self, button, frames):
            self.pressed.append((button, frames))

    emulator = Emulator()
    press_action(emulator, "left")
    press_action(emulator, "a")
    press_action(emulator, "down", menu=True)
    assert emulator.pressed == [("left", 16), ("a", 4), ("down", 4)]
