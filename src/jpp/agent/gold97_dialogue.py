"""Bound confirmation retries to actual changes in the visible conversation."""


class DialogueProgress:
    def __init__(self):
        self.reset()

    def reset(self):
        self.page = None
        self.attempts = 0

    def advance(self, state):
        page = (state.map_group, state.map_number, state.x, state.y,
                tuple(getattr(state, "screen_lines", ())))
        if page != self.page:
            self.page, self.attempts = page, 0
        self.attempts += 1
        if self.attempts > 6:
            return None
        return "b" if self.attempts > 4 else "a"
