"""Reachable investigations from observed sprites, terrain, and transitions."""

from ..route_progress import MAIN
from .gold97_navigation import STEPS
from .navigation_paths import paths
from .navigation_policy import prefer_discovery
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



def candidates(state, memory, terrain, *, excluded=(), reward_weights=None):
    key = f"{state.map_group:02X}:{state.map_number:02X}"
    data = memory.world["journey_strategy"]
    reachable = paths(state, memory, terrain, prefer_new=False)
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
        if speaker:
            # The adapter matched an observed self-introduction, not a sprite
            # index or somebody else mentioning this objective's participant.
            npc.update(category='npc', name=speaker, role='objective participant')
        ferry = ferry_speaker(state, milestone, npc)
        from .mine_guidance import rescue_speaker
        rescue = rescue_speaker(state, milestone, npc)
        speaker = speaker or ('missing girl' if rescue else 'Teknos ferry sailor' if ferry else None)
        if (npc["map"] != key
                or (not speaker and (npc["status"] != "pending"
                                     or (not npc.get("visible", True) and not npc.get("observed")
                                      and npc.get("category") not in {"item", "obstacle", "resource"})))):
            continue
        approaches = sorted(STEPS.items(), key=lambda entry: reachable.distances.get(
            (npc["cell"][0] - entry[1][0], npc["cell"][1] - entry[1][1]), float('inf')))
        for direction, (dx, dy) in approaches:
            cell = npc["cell"][0] - dx, npc["cell"][1] - dy
            if cell in reachable:
                npc["reachability"] = "reachable"
                reobserve = not npc.get('visible', True) and npc.get('category') not in {'item', 'obstacle', 'resource'}
                candidate = {"id": npc["id"], "kind": "explore" if reobserve else "talk", "cell": list(cell),
                               "direction": direction,
                               "category": npc.get('category'), "outcome": npc.get('outcome'),
                               "label": ('Recheck the last-seen object' if reobserve else
                                         'Collect the observed item' if npc.get('category') == 'item' else
                                         'Harvest the observed resource' if npc.get('category') == 'resource' else
                                         'Investigate the blocking object' if npc.get('category') == 'obstacle' else
                                         'Ask the sailor for the Teknos City ferry' if ferry else
                                         f"Challenge {speaker}" if speaker else "Talk to an unvisited sprite"),
                               "goal_interaction": bool(speaker), "ferry_interaction": ferry,
                               "rescue_interaction": rescue,
                               "reobserve_interaction": reobserve,
                               "completion": ("Pickup confirmed or resource verified empty"
                                              if npc.get('category') == 'resource' else
                                              "Pickup confirmed" if npc.get('category') == 'item' else
                                              "Dialogue observed and closed"), "map": key}
                from .navigation_memory import allowed_targets
                from .navigation_trace import unexhausted
                if (target_key(candidate) in excluded
                        or not allowed_targets(memory, milestone, [candidate])
                        or not unexhausted(memory, [candidate])):
                    continue  # A failed viewpoint does not rule out the person.
                result.append(candidate)
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
    from .discovery import known_exits
    portals = {tuple(e[:2]) for e in known_exits(state, terrain)}
    unexplored = [cell for cell in frontier_cells(reachable, terrain, visited) if cell not in portals and
                                   f"explore:{key}:{cell}" not in excluded]
    from .navigation_trace import unexhausted
    unexplored = [cell for cell in unexplored if unexhausted(memory, [
        {"map": key, "kind": "explore", "cell": list(cell), "direction": ""}])]
    distance = lambda cell: reachable.distances[cell]
    farther = {cell for cell in unexplored if 6 <= distance(cell) <= 10}
    selected = {}
    for cell in sorted(unexplored, key=lambda c: (c not in farther, -distance(c), c)):
        dx, dy = cell[0] - state.x, cell[1] - state.y
        sector = ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
        selected.setdefault(sector, cell)
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
    from .travel_atlas import atlas_exits
    mapped = [t for t in atlas_exits(state, reachable, excluded, terrain) if not exit_blocked(t, memory)]
    mapped_cells = {tuple(t['cell']) for t in mapped}
    result = [t for t in result if not (t['kind'] == 'exit' and
              t.get('destination_key') == '00:00' and tuple(t['cell']) in mapped_cells)]
    result.extend(mapped)
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
    from .hm_preparation import rank_preparation
    ranked = rank_preparation(ranked, state, milestone, weights['milestone'], memory)
    from .mine_guidance import rank_rescue
    ranked = rank_rescue(ranked, weights['milestone'])
    from .travel_atlas import rank_travel, rank_travel_frontier
    from .passage_navigation import mark_entry_returns
    ranked = mark_entry_returns(ranked, memory, state, milestone)
    ranked = rank_travel(ranked, state, milestone, weights['milestone'], memory)
    if getattr(terrain, 'seen', None) is not None:
        ranked = rank_travel_frontier(ranked, state, milestone, weights['milestone'], memory)
    from .navigation_trace import unexhausted
    from .navigation_memory import allowed_targets, target_evidence
    ranked = allowed_targets(memory, milestone, ranked)
    for target in ranked:
        target['destination_evidence'] = target_evidence(target, memory)
    ranked = unexhausted(memory, filter_cycles(prefer_discovery(ranked, memory), memory))
    for target in ranked:
        target['path_steps'] = reachable.distances.get(tuple(target['cell']), 0)
    return sorted(ranked, key=lambda t: (-t.get('journey_reward', 0),
                                        not t.get('unvisited_destination', False),
                                        t['path_steps']))



def target_options(target, state, memory, terrain, pending=None):
    origin = state.x, state.y
    if target["map"] != f"{state.map_group:02X}:{state.map_number:02X}":
        return {}
    from .interaction_refresh import refresh_interaction
    refresh_interaction(target, memory.world['journey_strategy']['npcs'])
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
        approaches = [(reachable.distances[(npc["cell"][0]-dx, npc["cell"][1]-dy)],
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
