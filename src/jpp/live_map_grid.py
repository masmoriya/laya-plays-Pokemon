"""Compact collision grid and shared map-coordinate overlays."""

import pygame

from .live_ui_colors import BG, GOOD, MUTED, PANEL, TEXT, WARN

STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def cell_kind(terrain, point):
    if terrain.tile(point) is None:
        return "unknown", ()
    allowed = tuple(d for d in STEPS if terrain.allows(point, d))
    return ("walk" if len(allowed) == 4 else "ledge" if allowed else "blocked"), allowed


class MapGrid:
    def __init__(self, ui):
        self.ui = ui
        self.key = None
        self.surface = None

    def draw(self, snapshot, view):
        terrain = snapshot.terrain
        key = (terrain.map_key, terrain.width, terrain.height, terrain.tiles, getattr(terrain, "seen", None), view.size)
        size = 12
        if self.key != key:
            source = pygame.Surface((terrain.width * size, terrain.height * size))
            source.fill(BG)
            for y in range(terrain.height):
                for x in range(terrain.width):
                    kind, allowed = cell_kind(terrain, (x, y))
                    rect = pygame.Rect(x * size, y * size, size, size)
                    color = {"walk": MUTED, "blocked": BG, "ledge": WARN,
                             "unknown": PANEL}[kind]
                    pygame.draw.rect(source, color, rect.inflate(-1, -1))
                    if kind == "ledge":
                        dx, dy = STEPS[allowed[0]]
                        cx, cy = rect.center
                        pygame.draw.polygon(source, BG, [
                            (cx + dx * 4, cy + dy * 4),
                            (cx - dx * 3 + dy * 3, cy - dy * 3 - dx * 3),
                            (cx - dx * 3 - dy * 3, cy - dy * 3 + dx * 3)])
            scale = min(view.width / source.get_width(), view.height / source.get_height())
            self.surface = pygame.transform.scale(source, (
                max(1, round(source.get_width() * scale)),
                max(1, round(source.get_height() * scale))))
            self.key = key
        target = self.surface.get_rect(center=view.center)
        self.ui.canvas.blit(self.surface, target)
        self.overlays(snapshot, target)

    def overlays(self, snapshot, target):
        terrain = snapshot.terrain
        key = f"{terrain.map_key[0]:02X}:{terrain.map_key[1]:02X}"
        sx, sy = target.width / terrain.width, target.height / terrain.height

        def center(x, y):
            return (target.x + round((x + .5) * sx),
                    target.y + round((y + .5) * sy))

        previous = self.ui.canvas.get_clip()
        self.ui.canvas.set_clip(target.clip(previous))
        try:
            from .live_map_markers import draw_objects
            seen = getattr(terrain, 'seen', None)
            trail = snapshot.trail[-48:]
            for start, end in zip(trail, trail[1:]):
                if (abs(start[0]-end[0])+abs(start[1]-end[1]) == 1
                        and (seen is None or start in seen and end in seen)):
                    pygame.draw.line(self.ui.canvas, TEXT, center(*start), center(*end), 1)
            draw_objects(self.ui, snapshot, center)
            from .live_map_markers import draw_marker
            for x, y, *_ in snapshot.exits:
                if 0 <= x < terrain.width and 0 <= y < terrain.height:
                    draw_marker(self.ui, center(x, y), 'warp', visible=False)
            destination = snapshot.destination
            if destination and destination[0] == terrain.map_key:
                x, y = destination[1]
                if 0 <= x < terrain.width and 0 <= y < terrain.height:
                    pygame.draw.circle(self.ui.canvas, TEXT, center(x, y),
                                       max(5, round(min(sx, sy) * .4)), width=2)
            position = center(*snapshot.position)
            pygame.draw.circle(self.ui.canvas, BG, position, 6)
            pygame.draw.circle(self.ui.canvas, GOOD, position, 4)
        finally:
            self.ui.canvas.set_clip(previous)
