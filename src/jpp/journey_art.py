"""Authentic Gold 97 milestone art read from the supplied cartridge."""

import pygame

from .pokemon_sprites import decompress_lz, _surface


# Anchors were checked against the supplied v6.1c cartridge. If another build
# moves the graphics, omit the artwork rather than showing the wrong trainer.
BADGE_OFFSET = 0x1E3CF
BADGE_ANCHOR = bytes.fromhex("0f0f3f30f1cec5bad5aad7ab")
TRAINER_POINTERS = 0x128000
TRAINER_ANCHOR = bytes.fromhex("1e116521f2581f9745218442")
PALETTE_OFFSET = 0xB0D6
PALETTE_ANCHOR = bytes.fromhex("3b3aa77c5c26f5085a3ee721")
BANK_SHIFT = 0x36
TRAINERS = {
    "Falkner": 0, "Whitney": 1, "Bugsy": 2, "Morty": 3,
    "Pryce": 4, "Jasmine": 5, "Okera": 6, "Red": 19,
    "Lorelei": 10, "Agatha": 12, "Giovanni": 13, "Koga": 14,
    "Lance": 15, "Blue": 60,
}


def _tiles(raw, width, height):
    """Decode row-major 2bpp tiles, preserving the cartridge's pixel shapes."""
    if len(raw) < width * height * 16:
        return None
    surface = pygame.Surface((width * 8, height * 8), pygame.SRCALPHA)
    colors = ((0, 0, 0, 0), (198, 217, 209), (99, 147, 151), (30, 53, 59))
    for tile_y in range(height):
        for tile_x in range(width):
            offset = (tile_y * width + tile_x) * 16
            for row in range(8):
                low, high = raw[offset + row * 2:offset + row * 2 + 2]
                for col in range(8):
                    shade = (low >> (7 - col) & 1) | ((high >> (7 - col) & 1) << 1)
                    surface.set_at((tile_x * 8 + col, tile_y * 8 + row), colors[shade])
    return surface


class JourneyArt:
    def __init__(self, rom=None):
        self.rom = rom or b""
        self.badges = {}
        self.portraits = {}
        self.badge_ready = self.rom[BADGE_OFFSET:BADGE_OFFSET + 12] == BADGE_ANCHOR
        self.trainer_ready = self.rom[TRAINER_POINTERS:TRAINER_POINTERS + 12] == TRAINER_ANCHOR
        self.palette_ready = self.rom[PALETTE_OFFSET:PALETTE_OFFSET + 12] == PALETTE_ANCHOR

    def _trainer_colors(self, index):
        if not self.palette_ready:
            return None
        offset = PALETTE_OFFSET + index * 4
        values = (int.from_bytes(self.rom[offset + i:offset + i + 2], "little") for i in (0, 2))
        return tuple(tuple((value >> shift & 31) * 255 // 31 for shift in (0, 5, 10)) + (255,)
                     for value in values)

    def badge(self, index):
        if not self.badge_ready or not 0 <= index < 8:
            return None
        if index not in self.badges:
            # The trainer-card sheet is two tiles wide and 11 badges tall.
            start = BADGE_OFFSET + index * 64
            self.badges[index] = _tiles(self.rom[start:start + 64], 2, 2)
        return self.badges[index]

    def portrait(self, name):
        if not self.trainer_ready or name not in TRAINERS:
            return None
        if name not in self.portraits:
            pointer = TRAINER_POINTERS + TRAINERS[name] * 3
            bank = self.rom[pointer] + BANK_SHIFT
            address = self.rom[pointer + 1] | self.rom[pointer + 2] << 8
            start = bank * 0x4000 + address - 0x4000
            raw = (decompress_lz(self.rom, start) if 0x4000 <= address < 0x8000
                   and 0 <= start < len(self.rom) else b"")
            self.portraits[name] = (_surface(raw, 7, self._trainer_colors(TRAINERS[name]))
                                    if len(raw) >= 784 else None)
        return self.portraits[name]
