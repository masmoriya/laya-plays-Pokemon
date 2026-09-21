"""Read-only storage projection for the fingerprinted v6.1c cartridge.

box_struct is 32 bytes; box is 0x450. Active Box SRAM moves five bytes
with this build's save block. Never read the stale saved copy of the active box.
"""
from .decode import Mon
from .gold97_catalog import item_name, move_name
from .gold97_data import _decode_name

ACTIVE_BOX = 0xAD15
CURRENT_BOX = 0xDB76
BOX_SIZE = 0x450


def storage(data, memory):
    try:
        current = memory[1, CURRENT_BOX] & 0x7f
        if current >= 14:
            return (), False, None
        roster = []
        for box in range(14):
            bank = 1 if box == current else 2 + box // 7
            address = ACTIVE_BOX if box == current else 0xA000 + (box % 7) * BOX_SIZE
            raw = bytes(memory[bank, address:address + BOX_SIZE])
            count = raw[0]
            if count > 20 or (count and raw[count + 1] != 255):
                return (), False, current
            for index in range(count):
                base = 22 + index * 32
                mon = raw[base:base + 32]
                species = raw[index + 1]
                if species != mon[0] or not 0 < species < len(data.names) or not 1 <= mon[31] <= 100:
                    return (), False, current
                info = data.species_data(species)
                indices = [i for i in range(4) if mon[2 + i]]
                nickname = _decode_name(raw[882 + 11 * index:893 + 11 * index])
                roster.append(Mon(slot=index + 1, species=data.name(species), species_id=species,
                                  level=mon[31], hp=0, max_hp=0, status='stored',
                                  types=info.types if info else (), species_data=info,
                                  moves=tuple(move_name(mon[2 + i]) for i in indices),
                                  pp=tuple(mon[23 + i] & 63 for i in indices),
                                  held_item=item_name(mon[1]), experience=int.from_bytes(mon[8:11], 'big'),
                                  growth_rate=getattr(info, 'growth_rate', None),
                                  identity=''.join(f'{mon[i]:02x}' for i in (6, 7, 21, 22, 29, 30)),
                                  nickname=nickname, storage_box=box, storage_slot=index))
        return tuple(roster), True, current
    except (IndexError, TypeError, ValueError, AttributeError):
        return (), False, None
