"""Legible current and last-seen objects on both map views."""
import pygame
from .live_ui_colors import BG, TEXT, WARN, GOOD


def draw_marker(ui, center, category, outcome='seen', visible=True):
    x, y = center
    resolved = outcome in {'collected', 'harvested', 'exhausted', 'defeated', 'conversed', 'moved'}
    color = GOOD if resolved else WARN if visible else TEXT
    pygame.draw.circle(ui.canvas, BG, center, 5)
    width = 0 if visible else 1
    if category in {'item', 'resource'}:
        pygame.draw.polygon(ui.canvas, color, [(x,y-4),(x+4,y),(x,y+4),(x-4,y)], width)
    elif category == 'obstacle':
        pygame.draw.rect(ui.canvas, color, pygame.Rect(x-3,y-3,7,7), width)
    elif category == 'npc':
        pygame.draw.circle(ui.canvas, color, center, 3, width)
    else:
        glyph = ui.tiny.render('?', True, color)
        ui.canvas.blit(glyph, glyph.get_rect(center=center))


def draw_objects(ui, snapshot, center):
    terrain = snapshot.terrain
    key = f'{terrain.map_key[0]:02X}:{terrain.map_key[1]:02X}'
    seen = getattr(terrain, 'seen', None)
    remembered = {}
    for obj in snapshot.objects:
        x, y = obj['cell']
        if (obj['map'] != key or not 0 <= x < terrain.width or not 0 <= y < terrain.height
                or not (obj.get('observed') or seen is None or (x,y) in seen)):
            continue
        # A collected ball is an outcome in the notebook, not a remaining object.
        if obj.get('outcome') == 'collected':
            continue
        remembered[obj['id']] = obj
        draw_marker(ui, center(x,y), obj.get('category', 'unknown'),
                    obj.get('outcome', 'seen'), obj.get('visible', False))
    for entity in snapshot.entities:
        x, y = entity.pixel_x/16, entity.pixel_y/16
        if entity.map_key == key and f'{key}/{entity.key}' not in remembered:
            draw_marker(ui, center(x,y), getattr(entity, 'kind', 'unknown'))
