"""Read-only story completion evidence for the exact supported cartridge.

Pinned gold97 revision 976507f9e6e605050384e9ec12e9651988ae7c46:
constants/event_flags.asm, maps/BoulderMines1F.asm, maps/TeknosCity.asm,
maps/TeknosAquarium2F.asm, maps/OaksLabEntrance.asm, maps/BrassTower5F.asm,
and maps/WestportGym.asm. No navigation or completion is inferred from
an NPC's name or a model assertion.
"""

_EVENT_FLAGS = 0xDA72
# The girl script rescues her; the city scene records the takeover warning;
# Aquarium 2F returns Whitney to her gym after the Rocket encounter.
_EVENTS = {12: 1977, 13: 277, 14: 278}


def story_milestones(memory, verified, map_key=None):
    if not verified:
        return ()
    observed = {step for step, flag in _EVENTS.items()
                if memory[_EVENT_FLAGS + flag // 8] & (1 << (flag % 8))}
    # Reconstruct missing notebook history from persistent cartridge evidence.
    # Starter received; the lab's post-rival scene (2/4); fifth-floor blessing;
    # and Bugsy defeated each prove their corresponding earlier visit.
    def event(flag):
        return bool(memory[_EVENT_FLAGS + flag // 8] & (1 << (flag % 8)))
    if event(32):
        observed.add(1)
        if memory[0xD987] in (2, 4):
            observed.add(2)
    if event(31):
        observed.update((3, 4))
    if event(1220):
        observed.add(9)
    if map_key in {(3, 13), (3, 14), (3, 15), (3, 44), (3, 45), (3, 46), (4, 7)}:
        observed.add(11)  # Route 120 / mine arrival proves arrival beyond Teknos.
    # The warning flag is initialized before the rescue and cleared on Route
    # 120. Only its post-rescue city scene is evidence of the takeover warning.
    if 12 not in observed or map_key != (4, 5):
        observed.discard(13)
    return tuple(sorted(observed))
