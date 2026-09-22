"""Load Jev's transparent pixel-art atlas for the live and stream UIs."""

from pathlib import Path

import pygame


STATE_ORDER = (
    "idle",
    "thinking",
    "decided",
    "battle",
    "celebrate",
    "confused",
    "recovering",
    "hurt",
    "sleep",
)
FRAME_SIZE = (96, 112)


def _default_path() -> Path:
    """Prefer the checkout asset, with a package-relative fallback for launchers."""
    checkout = Path("assets/jev/jev-spritesheet.png")
    if checkout.is_file():
        return checkout
    source = Path(__file__).resolve().parents[3] / checkout
    if source.is_file():
        return source
    return Path(__file__).resolve().parents[1] / "resources" / checkout


class JevSprites:
    """Small, optional sprite-sheet loader that never blocks headless play."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _default_path()
        self.frames: dict[str, tuple[pygame.Surface, ...]] = {}
        self._load()

    @property
    def available(self) -> bool:
        return bool(self.frames)

    def _load(self):
        if not self.path.is_file():
            return
        try:
            sheet = pygame.image.load(str(self.path))
            if pygame.display.get_surface() is not None:
                sheet = sheet.convert_alpha()
        except (pygame.error, OSError):
            return
        width, height = FRAME_SIZE
        for row, state in enumerate(STATE_ORDER):
            frames = []
            for column in range(4):
                area = pygame.Rect(column * width, row * height, width, height)
                if area.right > sheet.get_width() or area.bottom > sheet.get_height():
                    break
                frames.append(sheet.subsurface(area).copy())
            if frames:
                self.frames[state] = tuple(frames)

    def frame(self, state: str, index: int) -> pygame.Surface | None:
        """Return a frame, falling back to idle when a state is unavailable."""
        frames = self.frames.get(str(state).lower()) or self.frames.get("idle")
        if not frames:
            return None
        return frames[index % len(frames)]

    def draw(self, surface, state: str, index: int, destination) -> bool:
        """Draw a nearest-neighbour, aspect-preserving frame into ``destination``."""
        frame = self.frame(state, index)
        if frame is None:
            return False
        destination = pygame.Rect(destination)
        frame_width, frame_height = frame.get_size()
        scale = min(destination.width / frame_width, destination.height / frame_height)
        size = (max(1, round(frame_width * scale)), max(1, round(frame_height * scale)))
        scaled = pygame.transform.scale(frame, size)
        target = scaled.get_rect(midbottom=destination.midbottom)
        surface.blit(scaled, target)
        return True
