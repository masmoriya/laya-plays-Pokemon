"""Exit candidates grounded in current cartridge geometry and movement evidence."""

from ..gold97_catalog import map_details


def exit_blocked(target, memory):
    return [target["cell"], target.get("direction", "")] in memory.map(
        target["map"])["blocked"]


def exit_candidates(state, memory, reachable, excluded, terrain=None):
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    distance = lambda cell: abs(cell[0] - state.x) + abs(cell[1] - state.y)
    from .discovery import ObservedTerrain, known_exits
    geometry = known_exits(state, terrain)
    destinations = {f"{group:02X}:{number:02X}" for _, _, _, group, number in geometry}
    geometric = {}
    for x, y, direction, group, number in geometry:
        cell = (x, y)
        if not direction and terrain is not None:
            # Cartridge collision constants: directional warp carpets trigger
            # when stepping off, including carpets inside a larger map.
            direction = {0x70: "down", 0x76: "left", 0x78: "up", 0x7E: "right"}.get(
                terrain.tile(cell), "")
        # Bottom-row door mats (including elevators) trigger when walking
        # out of the room, not when walking sideways onto the warp tile.
        if not direction and y == state.map_height - 1:
            direction = 'down'
        identifier = f"geometry:{key}:{x}:{y}:{direction}"
        if cell not in reachable or identifier in excluded:
            continue
        reentry = None
        if not direction and cell == (state.x, state.y):
            from .gold97_navigation import STEPS
            portals = {tuple(e[:2]) for e in geometry}
            reentry = next(([x+dx, y+dy] for dx, dy in STEPS.values()
                            if (x+dx, y+dy) in reachable and (x+dx, y+dy) not in portals), None)
            if reentry is None:
                continue
        name = map_details(group, number)[0] if group and number else "Unknown destination"
        target = {"id": identifier, "kind": "exit", "cell": [x, y],
                  "direction": direction, "map": key, "destination": name,
                  "destination_key": f"{group:02X}:{number:02X}",
                  "label": f"Continue to {name}" if group and number else "Investigate the observed exit", "completion": "Observe a map transition"}
        if reentry is not None:
            target.update(reentry=reentry, landing_return=True,
                          label="Step off and return through the arrival ladder after local exploration")
        if exit_blocked(target, memory):
            continue
        geometric[x, y, group, number] = target
    result = list(geometric.values())
    connections = memory.world["journey_strategy"]["connections"]
    outbound = {(c["from"], c["to"]) for c in connections}
    geometry_cells = {tuple(exit[:2]) for exit in geometry}
    identifiers = set()
    for connection in connections:
        if connection["from"] == key:
            destination, cell = connection["to"], connection["at"]
            identifier = f"exit:{key}:{destination}"
            direction = connection.get("direction", "")
            label = f"Follow known exit to {_area_name(destination)}"
        elif connection["to"] == key and (key, connection["from"]) not in outbound:
            destination, cell = connection["from"], connection["arrival"]
            identifier = f"entry:{key}:{destination}"
            # An arrival is not proof of a reversible portal: doors often land
            # one tile outside, and scripts/healing can teleport across maps.
            # Current doorway geometry owns interior exits. At an actual map
            # boundary, investigate outward rather than reversing an old pose.
            if tuple(cell) in geometry_cells:
                continue
            direction = ("left" if cell[0] == 0 else
                         "right" if cell[0] == state.map_width - 1 else
                         "up" if cell[1] == 0 else
                         "down" if cell[1] == state.map_height - 1 else None)
            if direction is None:
                continue
            label = "Investigate the entrance back to the previous area"
        else:
            continue
        # Old checkpoints can contain transitions sampled during a fade or a
        # scripted relocation. A currently observed interior floor tile with
        # no portal cannot become an exit just because that history names it.
        if (isinstance(terrain, ObservedTerrain) and tuple(cell) in terrain.seen
                and tuple(cell) not in geometry_cells
                and 0 < cell[0] < state.map_width - 1
                and 0 < cell[1] < state.map_height - 1):
            continue
        # Observed transitions can retain a heading from before a warp. Never
        # let those records override exits decoded from the active cartridge.
        if (destination in destinations or tuple(cell) in geometry_cells or tuple(cell) not in reachable
                or identifier in excluded or identifier in identifiers):
            continue
        target = {"id": identifier, "kind": "exit", "cell": cell,
                  "direction": direction, "map": key,
                  "destination": _area_name(destination), "destination_key": destination,
                  "label": label, "completion": "Observe a map transition"}
        if not exit_blocked(target, memory):
            result.append(target)
            identifiers.add(identifier)
    return result


def _area_name(key):
    try:
        group, number = (int(part, 16) for part in key.split(":"))
    except (AttributeError, ValueError):
        return ""
    return map_details(group, number)[0]
