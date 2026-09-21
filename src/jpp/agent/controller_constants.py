"""Shared controller input timing and screen predicates."""

CONTINUE = object()
_STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_MOVE_HOLD_FRAMES = 36
_MENU_COOLDOWN_FRAMES = 45
_REVERSE = {"up": "down", "down": "up", "left": "right", "right": "left"}
# The ROM's verified Players House 2F warp is the only map-specific guard here;
# it gets the fresh run out of the starting room without prescribing the story.
_KNOWN_EXITS = {(0x14, 0x07): (7, 1)}
_WAIT_LIMIT = 3
_MAX_CAPTURE_ATTEMPTS = 3


def _visible_prompt(state):
    """A missing overworld view alone does not mean a dialogue is open."""
    lines = getattr(state, "screen_lines", ()) or ()
    return (any(line.strip() for line in lines[12:]) or
            (getattr(state, "screen_cursor", None) is not None and
             any(line.strip() for line in lines)))
