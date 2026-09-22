"""Advance visible dialogue until the rendered conversation changes or closes."""

from zlib import crc32


class DialogueProgress:
    def __init__(self):
        self.reset()

    def reset(self):
        self.page = None
        self.attempts = 0

    @staticmethod
    def _signature(state, frame=None):
        if frame is not None:
            # The textbox occupies the lower portion of the Game Boy frame. Its
            # pixels are authoritative when decoded tile text briefly flickers
            # between complete and partial rows.
            textbox = frame[-64:, :, :3]
            return (state.map_group, state.map_number, crc32(textbox.tobytes()))
        return (state.map_group, state.map_number, state.x, state.y,
                tuple(getattr(state, "screen_lines", ())))

    def advance(self, state, frame=None):
        page = self._signature(state, frame)
        if page != self.page:
            self.page, self.attempts = page, 0
        self.attempts += 1
        # A is the forward/confirm input. B can cancel a scripted interaction
        # or branch and must never be used merely because a frame was unchanged.
        return "a"
