"""Stable full-area observed map with remembered character markers."""

import pygame

from .live_ui_colors import ACCENT, BG, MUTED, PANEL, TEXT


class LiveMap:
    def __init__(self, ui):
        self.ui = ui
        self._cache_key = None
        self._terrain = None

    def draw(self, state, journey):
        box = pygame.Rect(994, 176, 422, 382)
        pygame.draw.rect(self.ui.canvas, PANEL, box, border_radius=6)
        self.ui.text("Explored map", (box.x + 14, box.y + 12), self.ui.small, MUTED)
        name = getattr(state, "area_name", None) or "Area unavailable"
        locality = getattr(state, "locality", "")
        label = f"{locality} · {name}" if locality and locality not in name else name
        self.ui.text(label, (box.x + 14, box.y + 33), self.ui.body_bold, TEXT,
                     max_width=box.width - 28)
        view = pygame.Rect(box.x + 14, box.y + 64, box.width - 28, box.height - 100)
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
        cache_key = (map_key, columns, rows, revision, len(cells))
        if self._cache_key != cache_key:
            terrain = pygame.Surface((columns * 8, rows * 8))
            terrain.fill(PANEL)  # unseen area stays masked but its full extent is visible
            for (x, y), (_, rgba) in cells.items():
                if not (0 <= x < columns and 0 <= y < rows):
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
        self.ui.canvas.blit(pygame.transform.scale(self._terrain.subsurface(source), size), target)
        previous_clip = self.ui.canvas.get_clip()
        self.ui.canvas.set_clip(view)
        self._location_border(state, map_key, target, source, scale)
        current = {entity.key for entity in self.ui.map_entities
                   if entity.map_key == map_key and self._in_bounds(entity, columns, rows)}
        remembered = getattr(journey, "entities", {}).get(map_key, {}) if journey else {}
        for entity_key, (pixel_x, pixel_y, rgba) in remembered.items():
            if entity_key not in current:
                self._sprite(target, source, scale, pixel_x, pixel_y, rgba, alpha=112)
        for entity in self.ui.map_entities:
            if entity.map_key == map_key and self._in_bounds(entity, columns, rows):
                self._sprite(target, source, scale, entity.pixel_x, entity.pixel_y, entity.rgba)
        player = getattr(self.ui, "player_marker", None)
        if player and player.map_key == map_key:
            self._sprite(target, source, scale, player.pixel_x, player.pixel_y, player.rgba)
        self.ui.canvas.set_clip(previous_clip)

    def _source_rect(self, state, columns, rows):
        """Return the complete observed map; the game view is already the close-up."""
        width, height = columns * 8, rows * 8
        return pygame.Rect(0, 0, width, height)

    def _location_border(self, state, map_key, target, source, scale):
        player = getattr(self.ui, "player_marker", None)
        if player and player.map_key == map_key:
            pixel_x, pixel_y = player.pixel_x, player.pixel_y
        else:
            x, y = getattr(state, "x", None), getattr(state, "y", None)
            if x is None or y is None:
                return
            pixel_x, pixel_y = x * 16, y * 16
        side = max(2, round(16 * scale))
        rect = pygame.Rect(target.x + round((pixel_x - source.x) * scale),
                           target.y + round((pixel_y - source.y) * scale), side, side)
        pygame.draw.rect(self.ui.canvas, ACCENT, rect, width=max(1, round(scale)))

    @staticmethod
    def _opaque_surface(rgba, size):
        pixels = bytearray(rgba)
        if len(pixels) == size[0] * size[1] * 4:
            pixels[3::4] = b"\xff" * (len(pixels) // 4)
        return pygame.image.frombuffer(bytes(pixels), size, "RGBA").copy()

    def _sprite(self, target, source, scale, pixel_x, pixel_y, rgba, *, alpha=None):
        if len(rgba) != 1024:
            return
        side = max(10, round(16 * scale))
        sprite = pygame.image.frombuffer(rgba, (16, 16), "RGBA").copy()
        self._clear_opaque_black_background(sprite)
        if alpha is not None:
            sprite.set_alpha(alpha)
        position = (target.x + round((pixel_x - source.x) * scale),
                    target.y + round((pixel_y - source.y) * scale))
        self.ui.canvas.blit(pygame.transform.scale(sprite, (side, side)), position)

    @staticmethod
    def _clear_opaque_black_background(sprite):
        """Remove large edge-connected black backdrops while keeping sprite outlines."""
        pixels = pygame.surfarray.pixels3d(sprite)
        alpha = pygame.surfarray.pixels_alpha(sprite)
        dark = {(x, y) for y in range(sprite.get_height()) for x in range(sprite.get_width())
                if alpha[x, y] and max(pixels[x, y]) <= 8}
        if len(dark) < 16:
            del pixels, alpha
            return
        edge = [(x, y) for x, y in dark
                if x in (0, sprite.get_width() - 1) or y in (0, sprite.get_height() - 1)]
        seen = set()
        for start in edge:
            if start in seen:
                continue
            component, stack = set(), [start]
            while stack:
                point = stack.pop()
                if point in seen or point not in dark:
                    continue
                seen.add(point)
                component.add(point)
                x, y = point
                stack.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
            if len(component) >= 16:
                for x, y in component:
                    alpha[x, y] = 0
        del pixels, alpha

    @staticmethod
    def _in_bounds(entity, columns, rows):
        return 0 <= entity.pixel_x < columns * 8 and 0 <= entity.pixel_y < rows * 8
