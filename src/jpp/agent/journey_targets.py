"""Reachable investigations from observed sprites, terrain, and transitions."""

import heapq
from itertools import count
import json
from functools import lru_cache

from ..route_progress import MAIN
from .gold97_navigation import STEPS
from .gold97_rewards import DEFAULT_WEIGHTS
from .gold97_services import CENTER_RETREAT_EXITS
from .journey_guidance import rank_candidates
from .experience import target_key
from .journey_objective import objective_speaker
from .journey_exits import exit_candidates, exit_blocked
from .journey_prerequisites import ferry_speaker, rank_prerequisites
from .discovery import frontier_cells
from .object_memory import classify, eligible, evidence_key
from .field_actions import experiments, strength_push


def paths(state, memory, terrain, *, prefer_new=True):
    """One observed-path search, preferring edges not repeatedly retraced."""
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    memory.expire_blocked(key)
    origin = (state.x, state.y)
    blocked = frozenset((tuple(p), d) for p, d in memory.map(key)["blocked"])
    objects = frozenset(tuple(n["cell"]) for n in memory.world.get("journey_strategy", {}).get(
        "npcs", {}).values() if n["map"] == key and n.get("outcome") != "collected"
        and (n.get("visible", False) or n.get("category") in {"item", "obstacle"}))
    from .navigation_trace import edge_costs
    from .discovery import known_exits
    portals = frozenset(tuple(e[:2]) for e in known_exits(state, terrain))
    return _paths(origin, state.map_width, state.map_height, terrain, blocked, objects,
                  edge_costs(memory, key) if prefer_new else (), portals)


@lru_cache(maxsize=32)
def _paths(origin, width, height, terrain, blocked, objects, costs=(), portals=frozenset()):
    prices = {(tuple(p), d): count for stamp, count in costs for p, d in [json.loads(stamp)]}
    found, distances = {origin: None}, {origin: 0}
    serial = count()
    queue = [(0, next(serial), origin)]
    while queue:
        cost, _, point = heapq.heappop(queue)
        if cost != distances[point] or (point in portals and point != origin):
            continue
        for direction, (dx, dy) in STEPS.items():
            target = point[0] + dx, point[1] + dy
            if (target in objects or (point, direction) in blocked
                    or not (0 <= target[0] < width and 0 <= target[1] < height)
                    or terrain is None or not terrain.allows(target, direction)):
                continue
            price = cost + 1 + min(6, prices.get((point, direction), 0))
            if price < distances.get(target, float('inf')):
                distances[target] = price
                found[target] = found[point] or direction
                heapq.heappush(queue, (price, next(serial), target))
    return found


def candidates(state, memory, terrain, *, excluded=(), reward_weights=None):
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    data = memory.world["journey_strategy"]
    reachable = paths(state, memory, terrain)
    result = []
    milestone = next((i for i in range(1, 128) if i not in
                      memory.world.get("route", {}).get("completed", [])), None)
    goal = MAIN.get(milestone, "Continue journey")
    for npc in data["npcs"].values():
        classify(npc)
        context = evidence_key(state, npc, memory)
        if (npc.get('category') == 'obstacle' and npc.get('outcome') == 'unresolved'
                and not experiments(state, npc, memory) and not strength_push(state, npc, memory)):
            npc['last_result'] = 'No untried relevant field move or push for this obstacle'
        if not eligible(npc, context, 'approach'):
            continue
        if not eligible(npc, context) and not (npc.get('category') == 'obstacle' and
                (experiments(state, npc, memory) or strength_push(state, npc, memory))):
            continue
        if npc['status'] == 'deferred' and eligible(npc, context):
            npc['status'] = 'pending'
        if (not npc.get('visible', True)
                and tuple(npc['cell']) in getattr(terrain, 'visible_objects', ())):
            continue  # The last-known location is already in view and empty.
        speaker = objective_speaker(npc, goal)
        ferry = ferry_speaker(state, milestone, npc)
        from .mine_guidance import rescue_speaker
        rescue = rescue_speaker(state, milestone, npc)
        speaker = speaker or ('missing girl' if rescue else 'Teknos ferry sailor' if ferry else None)
        if (npc["map"] != key or (npc["id"] in excluded and npc.get("category") not in {"item", "obstacle"})
                or (not speaker and (npc["status"] != "pending"
                                     or (not npc.get("visible", True) and not npc.get("observed")
                                      and npc.get("category") not in {"item", "obstacle"})))):
            continue
        approaches = sorted(STEPS.items(), key=lambda entry: (
            abs(npc["cell"][0] - entry[1][0] - state.x)
            + abs(npc["cell"][1] - entry[1][1] - state.y)))
        for direction, (dx, dy) in approaches:
            cell = npc["cell"][0] - dx, npc["cell"][1] - dy
            if cell in reachable:
                npc["reachability"] = "reachable"
                reobserve = not npc.get('visible', True) and npc.get('category') not in {'item', 'obstacle'}
                result.append({"id": npc["id"], "kind": "explore" if reobserve else "talk", "cell": list(cell),
                               "direction": direction,
                               "category": npc.get('category'), "outcome": npc.get('outcome'),
                               "label": ('Recheck the last-seen object' if reobserve else
                                         'Collect the observed item' if npc.get('category') == 'item' else
                                         'Investigate the blocking object' if npc.get('category') == 'obstacle' else
                                         'Ask the sailor for the Teknos City ferry' if ferry else
                                         f"Challenge {speaker}" if speaker else "Talk to an unvisited sprite"),
                               "goal_interaction": bool(speaker), "ferry_interaction": ferry,
                               "rescue_interaction": rescue,
                               "reobserve_interaction": reobserve,
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
    portals = {tuple(e[:2]) for e in getattr(terrain, "exits", ())}
    unexplored = [cell for cell in frontier_cells(reachable, terrain, visited) if cell not in portals and
                                   f"explore:{key}:{cell}" not in excluded]
    from .navigation_trace import unexhausted
    unexplored = [cell for cell in unexplored if unexhausted(memory, [
        {"map": key, "kind": "explore", "cell": list(cell), "direction": ""}])]
    # Investigate a small area per plan, rather than requesting Luna every tile.
    # New NPCs and dialogue still interrupt immediately through observations.
    distance = lambda cell: abs(cell[0] - state.x) + abs(cell[1] - state.y)
    farther = [cell for cell in unexplored if 6 <= distance(cell) <= 10]
    selected = {}
    for cell in sorted(farther or unexplored, key=distance, reverse=True):
        selected.setdefault(reachable[cell], cell)
    for cell in selected.values():
        identifier = f"explore:{key}:{cell}"
        if cell != (state.x, state.y) and identifier not in excluded:
            result.append({"id": identifier, "kind": "explore", "cell": list(cell),
                           "direction": "", "label": "Investigate unexplored ground",
                           "completion": "Reach the target tile", "map": key})
    # Always offer reachable exits alongside local leads; departure must not
    # require talking to everyone or visiting every tile first.
    result.extend(exit_candidates(state, memory, reachable, excluded, terrain))
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
    weights = reward_weights or DEFAULT_WEIGHTS
    result = [item for item in result if target_key(item) not in excluded
              or item.get("category") in {"item", "obstacle"}]
    ranked = rank_candidates(result, goal, weights["milestone"], state.area_name)
    goal_maps = set(data["route_maps"].get(str(milestone), ()))
    for target in ranked:
        destination = target.get("destination_key")
        if target.get('within_goal') and destination in goal_maps:
            target['journey_reward'] = max(0, target['journey_reward'] - weights['milestone'])
            target['reward_reason'] += '; objective room already visited'
        if (target.get("kind") == "exit" and destination
                and destination not in goal_maps
                and target.get("journey_reward", 0) > 0):
            target["route_frontier"] = True
            target["journey_reward"] += weights["discovery"]
            target["reward_reason"] += "; new map for the current Journey milestone"
    ranked.sort(key=lambda target: -target.get("journey_reward", 0))
    from .journey_routes import rank_known_routes
    ranked = rank_known_routes(ranked, state, memory, goal, weights['milestone'])
    ranked = rank_prerequisites(ranked, state, milestone, weights['milestone'])
    from .exploration_cycles import filter_cycles
    from .journey_guidance import rank_interactions
    ranked = rank_interactions(ranked, weights['milestone'])
    from .journey_hms import rank_hm_targets
    ranked = rank_hm_targets(ranked, state, milestone, weights['milestone'], memory)
    from .mine_guidance import rank_rescue
    ranked = rank_rescue(ranked, weights['milestone'])
    ranked.sort(key=lambda t: -t.get('journey_reward', 0))
    from .navigation_trace import unexhausted
    return unexhausted(memory, filter_cycles(prefer_discovery(ranked, memory), memory))


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
    if target["map"] != f"{state.map_group:02X}:{state.map_number:02X}":
        return {}
    if target["kind"] == "exit" and exit_blocked(target, memory):
        return {}
    if target["kind"] == "talk":
        npc = memory.world["journey_strategy"]["npcs"].get(target["id"])
        if npc:
            dx, dy = STEPS[target["direction"]]
            target["cell"] = [npc["cell"][0] - dx, npc["cell"][1] - dy]
    if target.get("reentry") and not target.get("reentry_done"):
        if list(origin) == target["reentry"]:
            target["reentry_done"] = True
        else:
            direction = paths(state, memory, terrain, prefer_new=False).get(tuple(target["reentry"]))
            return {direction: target["label"]} if direction else {}
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
    reachable = paths(state, memory, terrain, prefer_new=False)
    if target["kind"] == "talk" and destination not in reachable and npc:
        # A walking NPC can make the originally chosen side inaccessible.
        # Re-approach the same observed speaker from another reachable side.
        approaches = [(abs(npc["cell"][0]-dx-origin[0]) + abs(npc["cell"][1]-dy-origin[1]),
                       d, (npc["cell"][0]-dx, npc["cell"][1]-dy))
                      for d, (dx,dy) in STEPS.items()
                      if (npc["cell"][0]-dx, npc["cell"][1]-dy) in reachable]
        if approaches:
            _, target["direction"], destination = min(approaches)
            target["cell"] = list(destination)
            if destination == origin:
                return {target["direction"]: "Face the sprite", "a": "Talk to the sprite"}
    direction = reachable.get(destination)
    return {direction: target["label"]} if direction else {}
