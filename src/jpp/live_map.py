"""Live navigation grid with optional explored artwork."""

import pygame

from .live_ui_colors import BG, GOOD, MUTED, PANEL, TEXT, WARN
from .live_map_grid import MapGrid


class LiveMap:
    def __init__(self, ui):
        self.ui = ui
        self._cache_key = None
        self._terrain = None
        self.grid = MapGrid(ui)

    def draw(self, state, journey):
        box = pygame.Rect(994, 176, 422, 382)
        pygame.draw.rect(self.ui.canvas, PANEL, box, border_radius=6)
        self.ui.text("Navigation" if self.ui.map_mode == "grid" else "Explored imagery", (box.x + 14, box.y + 12), self.ui.small, MUTED)
        name = getattr(state, "area_name", None) or "Area unavailable"
        locality = getattr(state, "locality", "")
        label = f"{locality} · {name}" if locality and locality not in name else name
        self.ui.text(label, (box.x + 14, box.y + 33), self.ui.body_bold, TEXT,
                     max_width=box.width - 28)
        x, y = getattr(state, "x", None), getattr(state, "y", None)
        position = f"Position {x},{y}" if x is not None and y is not None else "Position unavailable"
        self.ui.text(position, (box.x + 14, box.y + 55), self.ui.small, MUTED)
        view = pygame.Rect(box.x + 14, box.y + 82, box.width - 28, box.height - 118)
        view.height -= 23
        snapshot = self.ui.map_state.snapshot
        if snapshot is None:
            self.ui.text(self.ui.map_state.status, view.center, self.ui.small, MUTED, center=True)
        elif self.ui.map_mode == "grid":
            self.grid.draw(snapshot, view)
        else:
            self._area(state, journey, view)
        from .live_map_markers import draw_marker
        for label, category, offset in (("NPC", "npc", 0), ("Item", "item", 70),
                                        ("Object", "obstacle", 133), ("Unknown", "unknown", 218),
                                        ("Warp", "warp", 290)):
            x = box.x + 19 + offset
            draw_marker(self.ui, (x, box.bottom-49), category)
            self.ui.text(label, (x+9, box.bottom-57), self.ui.tiny, MUTED)
        self.ui.text("Trail", (box.right-50, box.bottom-57), self.ui.tiny, TEXT)
        for mode, label, x, width in (("grid", "Grid", box.right - 145, 48),
                                       ("artwork", "Artwork", box.right - 91, 77)):
            self.ui.button(f"map_{mode}", label, pygame.Rect(x, box.y + 9, width, 23),
                           TEXT if self.ui.map_mode == mode else MUTED)
        self.ui.button("map_details", "Hide" if self.ui.map_details else "Details",
                       pygame.Rect(box.x + 14, box.bottom - 30, 70, 23), MUTED)
        if self.ui.map_details:
            group, number = getattr(state, "map_group", 0), getattr(state, "map_number", 0)
            self.ui.text(f"Map {group:02X}:{number:02X}",
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
        seen = getattr(self.ui.map_state.snapshot.terrain, 'seen', None)
        cache_key = (map_key, columns, rows, revision, len(cells), seen)
        if self._cache_key != cache_key:
            terrain = pygame.Surface((columns * 8, rows * 8))
            terrain.fill(PANEL)  # unseen area stays masked but its full extent is visible
            for (x, y), (_, rgba) in cells.items():
                if (not (0 <= x < columns and 0 <= y < rows)
                        or seen is not None and (x//2, y//2) not in seen):
                    continue
                # Terrain is a screenshot layer, never a transparent overlay. Some
                # emulator tile buffers carry an empty alpha channel, which would
                # otherwise leave a dark square wherever a sprite was captured.
                terrain.blit(self._opaque_surface(rgba, (8, 8)), (x * 8, y * 8))
            self._terrain, self._cache_key = terrain, cache_key
        source = self._source_rect(state, columns, rows)
        scale = min(view.width / source.width, view.height / source.height)
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        target = pygame.Rect(0, 0, *size)
        target.center = view.center
        crop = self._terrain.subsurface(source)
        rendered = (pygame.transform.scale(crop, size) if size[0] < crop.get_width()
                    or size[1] < crop.get_height()
                    else pygame.transform.scale_by(crop, scale))
        self.ui.canvas.blit(rendered, target)
        snapshot = self.ui.map_state.snapshot
        if snapshot:
            self.grid.overlays(snapshot, target)

    def _source_rect(self, state, columns, rows):
        """Show a readable neighborhood around the current tile."""
        width, height = columns * 8, rows * 8
        x, y = getattr(state, "x", None), getattr(state, "y", None)
        if x is None or y is None:
            return pygame.Rect(0, 0, width, height)

        # Keep enough surrounding terrain to navigate while preventing large maps
        # from being reduced to a few indistinct pixels in the compact panel.
        visible_width, visible_height = min(width, 224), min(height, 160)
        center_x, center_y = x * 16 + 8, y * 16 + 8
        left = max(0, min(width - visible_width, center_x - visible_width // 2))
        top = max(0, min(height - visible_height, center_y - visible_height // 2))
        return pygame.Rect(left, top, visible_width, visible_height)

    @staticmethod
    def _opaque_surface(rgba, size):
        pixels = bytearray(rgba)
        if len(pixels) == size[0] * size[1] * 4:
            pixels[3::4] = b"\xff" * (len(pixels) // 4)
        return pygame.image.frombuffer(bytes(pixels), size, "RGBA").copy()
