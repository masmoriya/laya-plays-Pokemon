"""Render a privacy-safe top-down map summary for visual route planning."""

from PIL import Image, ImageDraw


def render_navigation_overview(terrain, state, memory, next_map=None):
    """Show observed warps, mapped exits, traveled tiles, and the player."""
    if terrain is None or not getattr(terrain, 'width', 0) or not getattr(terrain, 'height', 0):
        return None
    if terrain.map_key != (state.map_group, state.map_number):
        return None
    scale, legend = 8, 24
    width, height = terrain.width, terrain.height
    map_width = width * scale
    canvas_width = max(map_width, 160)
    map_left = (canvas_width - map_width) // 2
    image = Image.new('RGB', (canvas_width, height * scale + legend), '#17232b')
    draw = ImageDraw.Draw(image)
    seen = getattr(terrain, 'seen', None)
    walls = {1, 7, 15, 18, 21, 26, 29, 39, 47, 98, 106, 255}
    walls.update(range(128, 133))
    walls.update(range(136, 141))
    walls.update(range(144, 160))
    water = {32, 33, 34, 36, 37, 38, 40, 41, 42, 44, 45, 46}
    water.update(range(48, 64))
    water.update(range(192, 208))
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    visited = {tuple(cell) for cell in memory.map(key).get('visited', ())}
    for y in range(height):
        for x in range(width):
            cell = (x, y)
            if seen is not None and cell not in seen:
                color = '#17232b'
            else:
                tile = terrain.tile(cell)
                color = ('#316f8b' if tile in water else '#29343d' if tile in walls
                         else '#9aabb2' if cell in visited else '#70838d')
            left = map_left + x * scale
            draw.rectangle((left, y * scale, left + scale - 1,
                            y * scale + scale - 1), fill=color)

    observed_warps = set()
    for x, y, *_ in getattr(terrain, 'exits', ()):
        if 0 <= x < width and 0 <= y < height:
            observed_warps.add((x, y))
            left = map_left + x * scale
            draw.rectangle((left + 1, y * scale + 1,
                            left + scale - 2, y * scale + scale - 2),
                           fill='#e6a550')
    collision = getattr(terrain, 'collision', terrain)
    warp_tiles = {0x70, 0x76, 0x78, 0x7E}
    for y in range(height):
        for x in range(width):
            if (x, y) not in observed_warps and collision.tile((x, y)) in warp_tiles:
                observed_warps.add((x, y))
                _diamond(draw, x, y, scale, '#e6a550', filled=True, offset_x=map_left)
    from .travel_atlas import atlas
    edges = atlas()['edges'].get(key, ())
    for edge in edges:
        if 'cell' not in edge:
            continue
        x, y = edge['cell']
        if 0 <= x < width and 0 <= y < height:
            _diamond(draw, x, y, scale, '#55d8d0', filled=False, offset_x=map_left)
    if next_map:
        for edge in edges:
            if edge['to'] != next_map or 'cell' not in edge:
                continue
            x, y = edge['cell']
            if 0 <= x < width and 0 <= y < height:
                _diamond(draw, x, y, scale, '#36d7b7', filled=True, offset_x=map_left)
    px, py = state.x, state.y
    if 0 <= px < width and 0 <= py < height:
        left = map_left + px * scale
        draw.ellipse((left + 1, py * scale + 1,
                      left + scale - 2, py * scale + scale - 2), fill='#ffd34f')
    first_y, second_y = height * scale + 2, height * scale + 12
    _legend_marker(draw, 3, first_y, '#9aabb2', 'square')
    draw.text((10, first_y), 'seen', fill='#9aabb2')
    _legend_marker(draw, 43, first_y, '#d5e6ec', 'square')
    draw.text((50, first_y), 'walked', fill='#d5e6ec')
    _legend_marker(draw, 94, first_y, '#ffd34f', 'circle')
    draw.text((101, first_y), 'player', fill='#ffd34f')
    _legend_marker(draw, 3, second_y, '#e6a550', 'diamond')
    draw.text((10, second_y), 'warp', fill='#e6a550')
    _legend_marker(draw, 43, second_y, '#55d8d0', 'outline')
    draw.text((50, second_y), 'map exit', fill='#55d8d0')
    _legend_marker(draw, 108, second_y, '#36d7b7', 'diamond')
    draw.text((115, second_y), 'next', fill='#36d7b7')
    return image


def _diamond(draw, x, y, scale, color, *, filled, offset_x=0):
    cx, cy = offset_x + x * scale + scale // 2, y * scale + scale // 2
    radius = max(2, scale // 2 - 1)
    points = [(cx, cy - radius), (cx + radius, cy),
              (cx, cy + radius), (cx - radius, cy)]
    draw.polygon(points, fill=color if filled else None,
                 outline=color if not filled else None)


def _legend_marker(draw, x, y, color, kind):
    if kind == 'diamond':
        draw.polygon(((x + 3, y), (x + 6, y + 3), (x + 3, y + 6),
                      (x, y + 3)), fill=color)
    elif kind == 'outline':
        draw.polygon(((x + 3, y), (x + 6, y + 3), (x + 3, y + 6),
                      (x, y + 3)), outline=color)
    elif kind == 'circle':
        draw.ellipse((x, y, x + 6, y + 6), fill=color)
    else:
        draw.rectangle((x, y, x + 6, y + 6), fill=color)
