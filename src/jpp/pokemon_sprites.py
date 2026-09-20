"""Load authentic front art from the user's Reforged cartridge, never bundled art."""

import hashlib
from pathlib import Path

import pygame

from .gold97_data import Gold97RomData


PIC_POINTERS = 0x48 * 0x4000  # Gold 97 pokecrystal.link: Pic Pointers at $48:4000
TRAINER_PIC_POINTERS = 0x4A * 0x4000  # Reforged trainer pointer table
PICS_FIX = 0x36
_FLIP = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


def decompress_lz(rom, start, limit=16384):
    """Bounded Gen 2 LZ command stream. Invalid addresses never yield artwork."""
    out = bytearray()
    pos = start
    while pos < len(rom) and len(out) < limit:
        header = rom[pos]
        pos += 1
        if header == 0xff:
            return bytes(out)
        if header & 0xe0 == 0xe0:
            if pos >= len(rom):
                break
            command = (header >> 2) & 7
            length = (((header & 3) << 8) | rom[pos]) + 1
            pos += 1
        else:
            command, length = header >> 5, (header & 31) + 1
        if not 0 < length <= 1024 or len(out) + length > limit:
            break
        if command == 0:
            out.extend(rom[pos:pos + length]); pos += length
        elif command in (1, 2):
            pattern = rom[pos:pos + command]
            if len(pattern) != command:
                break
            out.extend(pattern[i % command] for i in range(length))
            pos += command
        elif command == 3:
            out.extend(bytes(length))
        elif command in (4, 5, 6):
            if pos >= len(rom):
                break
            first = rom[pos]; pos += 1
            if first & 0x80:
                offset = len(out) - (first & 0x7f) - 1
            else:
                if pos >= len(rom):
                    break
                offset = (first << 8) | rom[pos]
                pos += 1
            for index in range(length):
                source = offset - index if command == 6 else offset + index
                if not 0 <= source < len(out):
                    return b""
                byte = out[source]
                out.append(_FLIP[byte] if command == 5 else byte)
        else:
            break
    return b""


def _front_dimensions(rom):
    # A verified species-and-stat anchor locates the 32-byte Reforged base table.
    anchor = bytes((155, 45, 54, 50, 60, 60, 40))  # Flambear
    start = 0
    while (found := rom.find(anchor, start)) >= 0:
        table = found - 154 * 32
        if table >= 0 and rom[table:table + 7] == bytes((1, 45, 49, 49, 45, 65, 65)):
            return table
        start = found + 1
    return None


def _palette_offset(rom):
    first = bytes((0xde, 0x46, 0xd0, 0x4d))
    start = 0
    while (found := rom.find(first, start)) >= 0:
        if rom[found:found + 4] == rom[found + 4:found + 8] and found + 254 * 8 <= len(rom):
            return found
        start = found + 1
    return None


def _palette(rom, offset, identifier):
    if offset is None:
        return ((191, 207, 211, 255), (108, 147, 159, 255))
    start = offset + identifier * 8
    colors = []
    for pos in (start, start + 2):
        value = rom[pos] | (rom[pos + 1] << 8)
        colors.append((value & 31, (value >> 5) & 31, (value >> 10) & 31))
    return tuple(tuple(component * 255 // 31 for component in rgb) + (255,) for rgb in colors)


def _trainer_palette(rom, offset, trainer_class):
    if offset < 0:
        return None
    start = offset + (trainer_class - 1) * 4
    if start + 4 > len(rom):
        return None
    colors = []
    for pos in (start, start + 2):
        value = int.from_bytes(rom[pos:pos + 2], "little")
        rgb = (value & 31, (value >> 5) & 31, (value >> 10) & 31)
        colors.append(tuple(component * 255 // 31 for component in rgb) + (255,))
    return tuple(colors)


def _surface(two_bpp, dimension, middle_colors=None):
    needed = dimension * dimension * 16
    if len(two_bpp) < needed:
        return None
    width = dimension * 8
    surface = pygame.Surface((width, width), pygame.SRCALPHA)
    colors = ((255, 255, 255, 255), *(middle_colors or ((191, 207, 211, 255),
                                               (108, 147, 159, 255))), (36, 45, 51, 255))
    for tx in range(dimension):
        for ty in range(dimension):
            base = (tx * dimension + ty) * 16  # source is column-major
            for row in range(8):
                low, high = two_bpp[base + row * 2:base + row * 2 + 2]
                for col in range(8):
                    shade = ((low >> (7 - col)) & 1) | (((high >> (7 - col)) & 1) << 1)
                    surface.set_at((tx * 8 + col, ty * 8 + row), colors[shade])
    return surface


class PokemonSprites:
    def __init__(self, rom_path, cache_root="data/pokemon_sprites"):
        self.rom = Path(rom_path).read_bytes()
        self.names = Gold97RomData.from_bytes(self.rom).names
        self.ids = {name.upper(): i for i, name in enumerate(self.names) if i}
        self.dimensions = _front_dimensions(self.rom)
        self.palettes = _palette_offset(self.rom)
        self.trainer_palettes = self.rom.find(bytes.fromhex("3b3aa77c5c26f508"))
        self.cache = Path(cache_root) / hashlib.sha256(self.rom).hexdigest()[:16]
        self.frames = {}

    def frame(self, species):
        identifier = self.ids.get(str(species).upper())
        if identifier is None:
            return None
        if identifier not in self.frames:
            self.frames[identifier] = self._load(identifier)
        frames = self.frames[identifier]
        if not frames:
            return None
        return frames[(pygame.time.get_ticks() // 360) % len(frames)]

    def trainer_frame(self, trainer_class):
        if not isinstance(trainer_class, int) or not 1 <= trainer_class <= 68:
            return None
        key = ("trainer", trainer_class)
        if key not in self.frames:
            self.frames[key] = self._load_trainer(trainer_class)
        return self.frames[key][0] if self.frames[key] else None

    def _load_trainer(self, trainer_class):
        pointer = TRAINER_PIC_POINTERS + (trainer_class - 1) * 3
        if pointer + 3 > len(self.rom):
            return ()
        bank = self.rom[pointer] + PICS_FIX
        address = int.from_bytes(self.rom[pointer + 1:pointer + 3], "little")
        start = bank * 0x4000 + address - 0x4000
        if not 0x4000 <= address < 0x8000 or start >= len(self.rom):
            return ()
        raw = decompress_lz(self.rom, start)
        surface = _surface(raw, 7, _trainer_palette(self.rom, self.trainer_palettes, trainer_class))
        return (surface,) if surface is not None else ()

    def _load(self, identifier):
        cached = self.cache / f"{identifier:03}-color-v3.png"
        if cached.is_file():
            try:
                return (pygame.image.load(str(cached)).convert_alpha(),)
            except pygame.error:
                return ()
        pointer = PIC_POINTERS + (identifier - 1) * 6
        if pointer + 3 > len(self.rom):
            return ()
        bank = self.rom[pointer] + PICS_FIX
        address = self.rom[pointer + 1] | (self.rom[pointer + 2] << 8)
        if not 0x4000 <= address < 0x8000:
            return ()
        start = bank * 0x4000 + address - 0x4000
        if start >= len(self.rom):
            return ()
        dimension = (self.rom[self.dimensions + (identifier - 1) * 32 + 17] >> 4
                     if self.dimensions is not None else 7)
        if not 4 <= dimension <= 7:
            return ()
        raw = decompress_lz(self.rom, start)
        surface = _surface(raw, dimension, _palette(self.rom, self.palettes, identifier))
        if surface is None:
            return ()
        self.cache.mkdir(parents=True, exist_ok=True)
        pygame.image.save(surface, str(cached))
        return (surface,)
