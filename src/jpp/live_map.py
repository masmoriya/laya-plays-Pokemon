"""Full-area observed map with transient overworld sprite overlays."""

import pygame

from .live_ui_colors import ACCENT, BG, MUTED, PANEL, SURFACE, TEXT


class LiveMap:
    def __init__(self, ui):
        self.ui = ui
        self._cache_key = None
        self._terrain = None

    def draw(self, state, journey, expanded=False):
        box = pygame.Rect(48, 48, 1344, 984) if expanded else pygame.Rect(994, 176, 422, 382)
        pygame.draw.rect(self.ui.canvas, PANEL, box, border_radius=6)
        self.ui.text("Explored map", (box.x + 14, box.y + 12), self.ui.small, MUTED)
        name = getattr(state, "area_name", None) or "Area unavailable"
        locality = getattr(state, "locality", "")
        label = f"{locality} · {name}" if locality and locality not in name else name
        self.ui.text(label, (box.x + 14, box.y + 33), self.ui.body_bold, TEXT,
                     max_width=box.width - (250 if expanded else 100))
        button_y = box.y + (14 if expanded else 10)
        self.ui.button("map_toggle", "Terrain" if self.ui.map_mode == "terrain" else "Paths",
                       pygame.Rect(box.right - (198 if expanded else 90), button_y, 76, 24), ACCENT)
        self.ui.button("map_expand", "Close" if expanded else "Expand",
                       pygame.Rect(box.right - 108, box.y + (14 if expanded else box.height - 30),
                                   76, 24), TEXT)
        view = pygame.Rect(box.x + 14, box.y + (76 if expanded else 64),
                           box.width - 28, box.height - (110 if expanded else 100))
        pygame.draw.rect(self.ui.canvas, BG, view, border_radius=4)
        self._area(state, journey, view)
        self.ui.button("map_details", "Hide" if self.ui.map_details else "Details",
                       pygame.Rect(box.x + 14, box.bottom - 30, 70, 23), MUTED)
        if self.ui.map_details:
            group, number = getattr(state, "map_group", 0), getattr(state, "map_number", 0)
            x, y = getattr(state, "x", None), getattr(state, "y", None)
            self.ui.text(f"{group:02X}:{number:02X}  ·  {x},{y}",
                         (box.x + 94, box.bottom - 27), self.ui.small, MUTED)

    def _area(self, state, journey, view):
        columns = getattr(state, "map_width", 0) * 2
        rows = getattr(state, "map_height", 0) * 2
        if not columns or not rows:
            self.ui.text("Map unavailable", view.center, self.ui.small, MUTED, center=True)
            return
        group, number = getattr(state, "map_group", 0), getattr(state, "map_number", 0)
        map_key = f"{group:02X}:{number:02X}"
        cells = journey.tiles.get(map_key, {}) if journey else {}
        revision = getattr(journey, "tile_revision", len(cells))
        cache_key = (map_key, columns, rows, self.ui.map_mode, revision, len(cells))
        if self._cache_key != cache_key:
            terrain = pygame.Surface((columns * 8, rows * 8))
            terrain.fill(PANEL)  # unseen area stays masked but its full extent is visible
            for (x, y), (_, rgba) in cells.items():
                if not (0 <= x < columns and 0 <= y < rows):
                    continue
                if self.ui.map_mode == "terrain":
                    terrain.blit(pygame.image.frombuffer(rgba, (8, 8), "RGBA"), (x * 8, y * 8))
                else:
                    pygame.draw.rect(terrain, SURFACE, (x * 8 + 1, y * 8 + 1, 6, 6))
            self._terrain, self._cache_key = terrain, cache_key
        scale = min(view.width / columns, view.height / rows)
        size = (max(1, round(columns * scale)), max(1, round(rows * scale)))
        target = pygame.Rect(0, 0, *size)
        target.center = view.center
        self.ui.canvas.blit(pygame.transform.scale(self._terrain, size), target)
        for pixel_x, pixel_y, rgba in self.ui.map_entities:
            if not (0 <= pixel_x < columns * 8 and 0 <= pixel_y < rows * 8):
                continue
            sprite = pygame.image.frombuffer(rgba, (8, 8), "RGBA")
            side = max(1, round(scale))
            position = (target.x + round(pixel_x * scale / 8),
                        target.y + round(pixel_y * scale / 8))
            self.ui.canvas.blit(pygame.transform.scale(sprite, (side, side)), position)
        x, y = getattr(state, "x", None), getattr(state, "y", None)
        if x is not None and y is not None:
            player = (target.x + round((2 * x + 1) * scale),
                      target.y + round((2 * y + 1) * scale))
            pygame.draw.circle(self.ui.canvas, ACCENT, player, max(3, round(scale)))
