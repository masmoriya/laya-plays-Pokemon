"""Read Gold 97's visible text and menu cursor from the cartridge tilemap."""

TILEMAP = 0xC4A0
WIDTH = 20
HEIGHT = 18
# The party cursor alternates between these two tiles while it blinks.  The
# command/menu cursor used by the existing tests is the latter; accepting both
# keeps the visible cursor usable during the short blink phase as well.
CURSORS = frozenset((0xEC, 0xED))
# Keep the original singular name available to callers that only need the
# stable command-cursor tile.
CURSOR = 0xED

_CHARS = {0x7F: " ", 0xE3: "-", 0xE6: "?", 0xE7: ".", 0xE8: "!",
          0xF4: ",", 0xF5: ":"}
_CHARS.update({0x80 + i: chr(65 + i) for i in range(26)})
_CHARS.update({0xA0 + i: chr(97 + i) for i in range(26)})
_CHARS.update({0xF6 + i: str(i) for i in range(10)})


def visible_rows(mem):
    """Return both text and raw tiles; menu markers use non-printing glyphs."""
    tiles = tuple(tuple(mem[TILEMAP + row * WIDTH + col]
                        for col in range(WIDTH)) for row in range(HEIGHT))
    lines = tuple("".join(_CHARS.get(tile, " ") for tile in row)
                  for row in tiles)
    return lines, tiles


def cursor_cell(tiles):
    # Party action menus retain the selected-mon marker behind the right menu.
    cursors = [(col, row) for row, cells in enumerate(tiles)
               for col, tile in enumerate(cells) if tile in CURSORS]
    return max(cursors, key=lambda point: point[0], default=None)


def _party_cursor(lines, tiles):
    """Return the one-based party slot under the visible party cursor.

    Gold 97 lays out up to six party slots in one vertical list.  CANCEL is
    drawn immediately after the final occupied slot, so its row is dynamic.
    The cursor is drawn in column zero, one tile to the left of the label.
    """
    cancel_rows = [row for row, line in enumerate(lines)
                   if "CANCEL" in line.upper()]
    if not cancel_rows:
        return None
    if any(tiles[row][0] in CURSORS for row in cancel_rows):
        return 0
    for slot, row in enumerate((1, 3, 5, 7, 9, 11), start=1):
        if row < len(tiles) and tiles[row][0] in CURSORS:
            return slot
    return None


def _looks_like_party(lines):
    """Recognize party rows even while a battle message overlays the bottom."""
    if not any("CANCEL" in line.upper() for line in lines):
        return False
    for row in (1, 3, 5, 7, 9, 11):
        if row + 1 >= len(lines):
            continue
        name = lines[row].strip()
        details = lines[row + 1].upper()
        if name and ("FNT" in details or any(char.isdigit() for char in details)):
            return True
    return False


def battle_menu(lines, tiles):
    """Distinguish command, move, party, and text screens before reading a cursor."""
    text = " ".join(" ".join(lines).upper().split())
    choices = {line.strip().upper() for line in lines}
    if ({'YES', 'NO'} <= choices and
            (('WILL' in text and 'CHANGE' in text) or 'SWITCH' in text)):
        return "switch_prompt", None
    if "USE NEXT" in text and "YES" in text and "NO" in text:
        return "forced_prompt", None
    if "FIGHT" in lines[14] and "PACK" in lines[16]:
        for row, y in ((14, 1), (16, 2)):
            for col, x in ((9, 1), (15, 2)):
                if tiles[row][col] in CURSORS:
                    return "command", (x, y)
        return "text", None
    if "TYPE" in lines[9]:
        for row in range(13, 17):
            if tiles[row][5] in CURSORS:
                return "moves", (1, row - 12)
        return "text", None
    if 'SWITCH' in text and 'STATS' in text and 'CANCEL' in text:
        rows = [i for i, line in enumerate(lines)
                if any(word in line.upper() for word in ('SWITCH', 'STATS', 'CANCEL'))]
        for row in rows:
            for col, tile in enumerate(tiles[row]):
                if col >= 8 and tile in CURSORS:
                    return 'party_action', (col, row)
        return 'party_action', None
    if _looks_like_party(lines) or _party_cursor(lines, tiles) is not None:
        slot = _party_cursor(lines, tiles)
        return "party", ((1, slot) if slot is not None else None)
    if any(any(tile for tile in row) for row in tiles):
        return "text", None
    return None, None
