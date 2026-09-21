"""Text clipping must never block the emulator's UI thread."""
from types import SimpleNamespace

import pygame
import pytest

from jpp.live_ui import LiveUI


@pytest.mark.parametrize(('value', 'width', 'expected'), [
    ('Short', 50, 'Short'),
    ('Long status message', 60, 'Long …'),
    ('Already clipped…', 50, 'Alre…'),
    ('Long status', 10, '…'),
    ('Long status', 9, ''),
    ('Long status', 0, ''),
    ('Long status', -1, ''),
    ('', 10, ''),
    ('x' * 10000, 50, 'xxxx…'),
])
def test_text_clipping_is_bounded_and_fits(value, width, expected):
    class Font:
        calls = 0
        rendered = None

        def size(self, text):
            self.calls += 1
            assert self.calls <= 20, 'Text clipping stopped making progress'
            return len(text) * 10, 10

        def render(self, text, *_args):
            self.rendered = text
            return pygame.Surface((max(1, len(text) * 10), 10))

    font = Font()
    ui = SimpleNamespace(body=font, canvas=pygame.Surface((100, 20)))
    LiveUI.text(ui, value, (0, 0), max_width=width)
    assert font.rendered == expected
