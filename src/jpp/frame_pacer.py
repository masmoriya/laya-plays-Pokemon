"""Pace complete emulator frames after rendering and audio work."""

import time


GAME_FRAMES_PER_SECOND = 59.7275


class FramePacer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.deadline = time.monotonic()

    def wait(self, speed):
        interval = 1 / (GAME_FRAMES_PER_SECOND * speed)
        self.deadline += interval
        remaining = self.deadline - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        else:
            self.deadline = time.monotonic()
