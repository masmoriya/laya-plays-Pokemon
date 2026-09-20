"""1920x1080 Game Boy hero + compact Jev telemetry compositor."""

import pygame

from ..character.animation import Animation
from ..character.sprites import JevSprites


WIDTH, HEIGHT = 1920, 1080
GAME_RECT = pygame.Rect(30, 30, 1280, 960)
PANEL = pygame.Rect(1340, 30, 550, 960)


class Compositor:
    def __init__(self, live=True):
        pygame.init()
        self.surface = pygame.Surface((WIDTH, HEIGHT))
        self.font = pygame.font.SysFont("Menlo, Monaco, monospace", 24)
        self.head = pygame.font.SysFont("Menlo, Monaco, monospace", 36, bold=True)
        self.animation = Animation()
        self.jev_sprites = JevSprites()
        self.live = live
        self.progress = {}
        self.thoughts = {"jev": "No live commentary yet", "luna": "No live commentary yet"}
        self.thought = self.thoughts["jev"]  # compatibility for existing callers

    def update(self, progress=None, thought=None, event_type=None, luna_thought=None):
        self.progress = progress or self.progress
        if thought:
            self.thoughts["jev"] = thought
            self.thought = thought
        if luna_thought:
            self.thoughts["luna"] = luna_thought
        if event_type:
            self.animation.handle_event(event_type)

    def draw(self, frame=None):
        self.surface.fill((19, 28, 35))
        pygame.draw.rect(self.surface, (36, 48, 57), GAME_RECT, border_radius=8)
        if frame is not None:
            image = pygame.surfarray.make_surface(frame.swapaxes(0, 1)[:, :, :3])
            self.surface.blit(pygame.transform.scale(image, GAME_RECT.size), GAME_RECT)
        else:
            self._text("Waiting for Game Boy…", GAME_RECT.center, center=True, color=(158, 177, 179))
        pygame.draw.rect(self.surface, (28, 39, 46), PANEL, border_radius=8)
        self._draw_panel()
        return self.surface

    def _draw_panel(self):
        x, y = PANEL.x + 32, PANEL.y + 30
        self._text("JEV", (x, y), self.head, (245, 223, 144))
        self._text("AI TRAINER", (x, y + 48), self.font, (157, 182, 183))
        self._draw_jev((PANEL.right - 150, y + 20))
        state = str(self.animation.state).upper()
        self._text(f"STATE  {state}", (x, y + 115), self.font, (245, 223, 144))
        goal = self.progress.get("current_objective", "Continue journey")
        self._text("CURRENT GOAL", (x, y + 175), self.font, (157, 182, 183))
        self._text(str(goal)[:30], (x, y + 212), self.font, (238, 238, 220))
        badges = self.progress.get("badges", ())
        self._text("BADGES", (x, y + 280), self.font, (157, 182, 183))
        self._text(" ".join("●" if i < len(badges) else "○" for i in range(8)), (x, y + 318), self.head, (245, 223, 144))
        self._text("TEAM", (x, y + 385), self.font, (157, 182, 183))
        for i, mon in enumerate(self.progress.get("party", ())[:6]):
            self._text(f"{mon.get('species','?')[:10]:10} LV{mon.get('level', 0):02}", (x, y + 425 + i * 34), self.font, (238, 238, 220))
        self._text("THOUGHT STREAM", (x, y + 650), self.font, (157, 182, 183))
        for i, name in enumerate(("luna", "jev")):
            thought = self.thoughts[name].replace("\n", " ")[:34]
            self._text(name.upper(), (x, y + 690 + i * 48), self.font, (245, 223, 144) if name == "luna" else (137, 204, 143))
            self._text(thought, (x + 90, y + 690 + i * 48), self.font, (238, 238, 220))
        run = self.progress.get("run_seconds", 0)
        self._text(f"RUN {int(run // 86400):02}D {int(run % 86400 // 3600):02}H", (x, y + 828), self.font, (238, 238, 220))

    def _draw_jev(self, origin):
        state = getattr(self.animation.state, "value", str(self.animation.state))
        if self.jev_sprites.draw(
            self.surface,
            state,
            self.animation.frame(),
            pygame.Rect(origin[0] - 18, origin[1] - 10, 150, 170),
        ):
            return
        # Original trainer silhouette, no borrowed character art. Scale 5x pixel blocks.
        ox, oy = origin
        palette = {(1, 0): (35, 35, 45), (2, 0): (35, 35, 45), (1, 1): (224, 167, 121), (2, 1): (224, 167, 121), (0, 2): (47, 73, 89), (1, 2): (47, 73, 89), (2, 2): (47, 73, 89), (3, 2): (47, 73, 89), (1, 3): (47, 73, 89), (2, 3): (47, 73, 89), (1, 4): (224, 167, 121), (2, 4): (224, 167, 121)}
        scale = 20
        bob = self.animation.frame() % 2
        for (x, y), color in palette.items():
            pygame.draw.rect(self.surface, color, (ox + x * scale, oy + (y + bob) * scale, scale, scale))

    def _text(self, value, pos, font=None, color=(238, 238, 220), center=False):
        font = font or self.font
        image = font.render(str(value), True, color)
        rect = image.get_rect(center=pos) if center else image.get_rect(topleft=pos)
        self.surface.blit(image, rect)
