"""Reachable investigations from observed sprites, terrain, and transitions."""

from collections import deque
from functools import lru_cache

from ..gold97_catalog import map_details
from ..route_progress import MAIN
from .gold97_navigation import STEPS
from .gold97_rewards import DEFAULT_WEIGHTS
from .gold97_services import CENTER_RETREAT_EXITS
from .journey_guidance import rank_candidates
from .experience import target_key


def paths(state, memory, terrain):
    """One collision-aware BFS, reused across all candidate targets."""
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    origin = (state.x, state.y)
    blocked = frozenset((tuple(p), d) for p, d in memory.map(key)["blocked"])
    objects = frozenset(tuple(n["cell"]) for n in memory.world.get("journey_strategy", {}).get(
        "npcs", {}).values() if n["map"] == key and n.get("visible", False))
    return _paths(origin, state.map_width, state.map_height, terrain, blocked, objects)


@lru_cache(maxsize=32)
def _paths(origin, width, height, terrain, blocked, objects):
    found = {origin: None}
    queue = deque([origin])
    while queue:
        point = queue.popleft()
        for direction, (dx, dy) in STEPS.items():
            target = point[0] + dx, point[1] + dy
            if (target in found or target in objects or (point, direction) in blocked
                    or not (0 <= target[0] < width and 0 <= target[1] < height)
                    or terrain is None or not terrain.allows(target, direction)):
                continue
            found[target] = found[point] or direction
            queue.append(target)
    return found


def _area_name(key):
    try:
        group, number = (int(part, 16) for part in key.split(":"))
    except (AttributeError, ValueError):
        return ""
    return map_details(group, number)[0]


def candidates(state, memory, terrain, *, excluded=(), reward_weights=None):
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    data = memory.world["journey_strategy"]
    reachable = paths(state, memory, terrain)
    result = []
    milestone = next((i for i in range(1, 128) if i not in
                      memory.world.get("route", {}).get("completed", [])), None)
    for npc in data["npcs"].values():
        if (npc["map"] != key or npc["status"] != "pending" or npc["id"] in excluded
                or not npc.get("visible", True)):
            continue
        approaches = sorted(STEPS.items(), key=lambda entry: (
            abs(npc["cell"][0] - entry[1][0] - state.x)
            + abs(npc["cell"][1] - entry[1][1] - state.y)))
        for direction, (dx, dy) in approaches:
            cell = npc["cell"][0] - dx, npc["cell"][1] - dy
            if cell in reachable:
                npc["reachability"] = "reachable"
                result.append({"id": npc["id"], "kind": "talk", "cell": list(cell),
                               "direction": direction, "label": "Talk to an unvisited sprite",
                               "completion": "Dialogue observed and closed", "map": key})
                break
        else:
            npc["reachability"] = "unreachable from the current position"
    # Tower geometry already verified by this adapter is a known exit, not a
    # story spoiler. Once its Journey milestone is past, return toward town.
    retreat = CENTER_RETREAT_EXITS.get((state.map_group, state.map_number))
    if retreat and memory.world.get("route", {}).get("completed", []) and 4 in memory.world["route"]["completed"]:
        identifier = f"exit:return:{key}"
        if tuple(retreat[0]) in reachable and identifier not in excluded:
            result.append({"id": identifier, "kind": "exit", "cell": list(retreat[0]),
                           "direction": retreat[1], "map": key,
                           "destination": "Pagota City",
                           "label": "Leave the completed tower and investigate Pagota",
                           "completion": "Observe a map transition"})
    visited = {tuple(p) for p in memory.map(key)["visited"]}
    unexplored = [] if result else [cell for cell in reachable if cell not in visited and
                                   f"explore:{key}:{cell}" not in excluded]
    # Investigate a small area per plan, rather than requesting Luna every tile.
    # New NPCs and dialogue still interrupt immediately through observations.
    distance = lambda cell: abs(cell[0] - state.x) + abs(cell[1] - state.y)
    farther = [cell for cell in unexplored if 6 <= distance(cell) <= 10]
    selected = {}
    for cell in sorted(farther or unexplored, key=distance, reverse=True):
        selected.setdefault(reachable[cell], cell)
    for cell in selected.values():
        identifier = f"explore:{key}:{cell}"
        if cell not in visited and identifier not in excluded:
            result.append({"id": identifier, "kind": "explore", "cell": list(cell),
                           "direction": "", "label": "Investigate unexplored ground",
                           "completion": "Reach the target tile", "map": key})
    # Always offer reachable exits alongside local leads; departure must not
    # require talking to everyone or visiting every tile first.
    geometric = {}
    for x, y, direction, group, number in getattr(state, 'map_exits', ()):
        cell = (x, y)
        identifier = f'geometry:{key}:{x}:{y}:{direction}'
        if cell not in reachable or identifier in excluded:
            continue
        if not direction and cell == (state.x, state.y):
            continue  # A warp must be approached, not repeatedly confirmed.
        target = {'id': identifier, 'kind': 'exit', 'cell': [x, y],
                  'direction': direction, 'map': key,
                  'destination': map_details(group, number)[0],
                  'destination_key': f'{group:02X}:{number:02X}',
                  'label': f'Continue to {map_details(group, number)[0]}',
                  'completion': 'Observe a map transition'}
        destination = (group, number)
        old = geometric.get(destination)
        if old is None or distance(cell) < distance(tuple(old['cell'])):
            geometric[destination] = target
    result.extend(geometric.values())
    for connection in data["connections"]:
        if connection["from"] == key and tuple(connection["at"]) in reachable:
            identifier = f"exit:{key}:{connection['to']}"
            if identifier not in excluded:
                result.append({"id": identifier, "kind": "exit", "cell": connection["at"],
                               "destination": _area_name(connection['to']),
                               "destination_key": connection['to'],
                               "direction": connection.get("direction", ""),
                               "label": f"Follow known exit to {_area_name(connection['to'])}",
                               "completion": "Observe a map transition", "map": key})
        elif connection["to"] == key and tuple(connection["arrival"]) in reachable:
            identifier = f"entry:{key}:{connection['from']}"
            if identifier not in excluded:
                reverse = {"up": "down", "down": "up", "left": "right", "right": "left"}
                result.append({"id": identifier, "kind": "exit", "cell": connection["arrival"],
                               "destination": _area_name(connection['from']),
                               "destination_key": connection['from'],
                               "direction": reverse.get(connection.get("direction"), "down"),
                               "label": "Investigate the entrance back to the previous area",
                               "completion": "Observe a map transition", "map": key})
    # Curated v6.1c cartridge-event guidance is revealed only after local leads.
    # It supplies geometry, never an invented Bill location or completion claim.
    retreat = CENTER_RETREAT_EXITS.get((state.map_group, state.map_number))
    if not result and retreat and tuple(retreat[0]) in reachable:
        identifier = f"guide:return:{key}"
        if identifier not in excluded:
            result.append({"id": identifier, "kind": "exit", "cell": list(retreat[0]),
                           "direction": retreat[1], "map": key,
                           "destination": "Pagota City",
                           "label": "Return toward Pagota via the tower exit",
                           "source": "Gold 97 v6.1c cartridge map events: gold97_services.py",
                           "completion": "Observe a map transition"})
    goal = MAIN.get(milestone, "Continue journey")
    weights = reward_weights or DEFAULT_WEIGHTS
    result = [item for item in result if target_key(item) not in excluded]
    ranked = rank_candidates(result, goal, weights["milestone"], state.area_name)
    return prefer_discovery(ranked, memory)


def prefer_discovery(targets, memory):
    """Suppress incidental returns when a reachable new destination exists."""
    known = {key for key, area in memory.world['maps'].items() if area.get('visited')}
    for connection in memory.world['journey_strategy']['connections']:
        known.update((connection['from'], connection['to']))
    for target in targets:
        if target.get('destination_key'):
            target['unvisited_destination'] = target['destination_key'] not in known
    novel = [target for target in targets if target.get('unvisited_destination')]
    if not novel:
        return targets
    # Preserve Journey reward order; novelty only breaks equal-reward ties.
    novel_ids = {target['id'] for target in novel}
    return sorted(targets, key=lambda target: (
        -target.get('journey_reward', 0), target['id'] not in novel_ids))


def target_options(target, state, memory, terrain, pending=None):
    origin = state.x, state.y
    if target["kind"] == "talk":
        npc = memory.world["journey_strategy"]["npcs"].get(target["id"])
        if npc:
            dx, dy = STEPS[target["direction"]]
            target["cell"] = [npc["cell"][0] - dx, npc["cell"][1] - dy]
    destination = tuple(target["cell"])
    if origin == destination:
        if target["kind"] == "talk":
            if pending:
                return {}
            # Facing is explicitly established by the executor before pressing A.
            return {target["direction"]: "Face the sprite", "a": "Talk to the sprite"}
        if target["kind"] == "exit" and target["direction"]:
            return {target["direction"]: target["label"]}
        return {}
    direction = paths(state, memory, terrain).get(destination)
    return {direction: target["label"]} if direction else {}
