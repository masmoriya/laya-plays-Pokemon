"""Compact planner context and live journey summaries."""

from ..route_progress import MAIN
from .journey_guidance import _terms, _GENERIC
from .journey_prerequisites import prerequisite_context


def objective_clues(clues, goal):
    terms = _terms(goal) - _GENERIC - {"toward", "return", "situation", "receive", "call", "about", "professor"}
    return [clue for clue in clues if terms & _terms(clue["text"])]


def strategy_context(self, state):
    goal = MAIN.get(self.owner.route.now, "Journey complete")
    words = {word.strip(".,").lower() for word in goal.split() if len(word) > 3}
    clues = objective_clues(self.data["clues"], goal)
    relevant = [clue for clue in clues[:-20]
                if any(word in clue["text"].lower() for word in words)]
    snapshot = self.owner.map_state.snapshot
    navigation = ({'position': snapshot.position, 'exits': snapshot.exits,
                   'frame': snapshot.frame_number, 'destination': snapshot.destination,
                   'fresh': self.owner.map_state.status == '' and not state.in_battle,
                   'entities': [{'key': e.key, 'cell': [e.pixel_x // 16, e.pixel_y // 16]} for e in snapshot.entities],
                   'nearby_terrain': [[x,y,snapshot.terrain.tile((x,y))]
                     for y in range(max(0,state.y-2), min(snapshot.terrain.height,state.y+3))
                     for x in range(max(0,state.x-2), min(snapshot.terrain.width,state.x+3))],
                   }
                  if snapshot else None)
    goal = MAIN.get(self.owner.route.now, "Journey complete")
    directive = (
        f"A verified Journey milestone is worth "
        f"{self.owner.rewards.weights['milestone']} reward points. Treat reward as one "
        "signal alongside direct goal progress, route distance, new areas, and evidence. "
        "Prefer a reachable candidate that advances the active goal when its route is clear. "
        "Follow the travel route. Dialogue is an observation, not automatically a quest or unfinished task. "
        "Only pursue dialogue that gives concrete evidence for the current objective. "
        "An interaction is not proof that an obstacle is resolved. "
        "Do not trade milestone progress for unrelated buildings, services, "
        "optional rooms, training, or exhaustive map coverage."
    )
    if self.owner.training.enabled:
        directive += (" Training is enabled by the player: fight suitable wild encounters, "
                      "develop lower-level partners, and allow Pokémon Center recovery detours. "
                      "Retain the current milestone and resume the journey after healing.")
    scope = self.owner.route.now
    guide = self.owner.memory.experience.active_guide(scope)
    remembered = [item for item in self.owner.memory.experience.operator_messages(20)
                  if item["kind"] == "remember"][:6]
    lean = self.owner.memory.experience.lean_context(scope)
    route_progress = {
        "milestone": scope,
        "visited_maps": self.data["route_maps"].get(str(scope), ())[-12:],
        "arrived_from": self.arrived_from,
    }
    if lean and navigation:
        navigation = {key: navigation.get(key) for key in
                      ("position", "exits", "destination", "fresh", "connections")
                      if navigation.get(key) not in (None, [], ())}
    from .journey_hms import hm_journey
    hm_steps = hm_journey(state, scope)
    from ..journey_checklist import journey_steps
    prerequisite = prerequisite_context(state, scope)
    from .planner_world import world_context
    from .travel_atlas import travel_context
    from .navigation_memory import navigation_memory
    from .progress_contract import contract
    return {"progress": contract(self.owner, state), "navigation_memory": navigation_memory(self, state), "travel": travel_context(state, scope), "world": world_context(self.owner, state), "hm_journey": hm_steps, "navigation": navigation, "goal": goal, "directive": directive,
            "prerequisites": prerequisite,
            "journey_steps": journey_steps(hm_steps, prerequisite),
            "context_mode": "lean" if lean else "standard",
            "route_progress": route_progress,
            "operator_guidance": guide,
            "operator_notes": remembered,
            "map": state.area_name,
            "candidates": (self.payload or {}).get("candidates", []),
            "clues": ((relevant[-2:] + clues[-2:]) if lean else
                      relevant[-6:] + clues[-8:]),
            "failed_attempts": self.owner.memory.experience.failures(self.owner.route.now)[-1 if lean else -6:],
            "interactions": [{**npc, "pages": npc["pages"][-2:]}
                             for npc in list(self.data["npcs"].values())
                             if npc['map'] == f'{state.map_group:02X}:{state.map_number:02X}'][-4 if lean else -12:],
            "team": {"training": self.owner.training.summary(state, self.owner.rewards.weights), "party": [{
                        "species": m.species, "level": m.level, "hp": m.hp,
                        "max_hp": getattr(m, "max_hp", None), "status": getattr(m, "status", None),
                        "types": list(getattr(m, "types", ())), "stats": list(getattr(m, "stats", ())),
                        "moves": list(m.moves), "pp": list(getattr(m, "pp", ())),
                        "max_pp": list(getattr(m, "max_pp", ())),
                        "held_item": getattr(m, "held_item", None),
                    } for m in getattr(state, "party", ())],
                     "rewards": self.owner.rewards.summary()},
            "battle": _battle_context(state),
            "connections": [c for c in self.data['connections']
                            if f'{state.map_group:02X}:{state.map_number:02X}' in (c['from'], c['to'])][-12:],
            "recent": self.data["events"][-2 if lean else -12:],
            "questions": ["Which candidate best advances the active goal from this location?",
                          "What observable result proves progress toward this milestone?"]}


def _battle_context(state):
    battle = getattr(state, 'battle', None)
    if battle is None:
        return {"kind": "none"}

    def mon(value):
        if value is None:
            return None
        return {"species": getattr(value, "species", None),
                "level": getattr(value, "level", None), "hp": getattr(value, "hp", None),
                "max_hp": getattr(value, "max_hp", None), "status": getattr(value, "status", None),
                "types": list(getattr(value, "types", ())), "stats": list(getattr(value, "stats", ())),
                "moves": list(getattr(value, "moves", ())), "pp": list(getattr(value, "pp", ())),
                "stages": list(getattr(value, "stages", ())) }

    return {"kind": getattr(battle, "kind", "none"), "active": mon(getattr(battle, "active", None)),
            "opponent": mon(getattr(battle, "opponent", None)),
            "active_slot": getattr(state, "active_slot", None),
            "menu": getattr(state, "battle_menu_kind", None),
            "escape_allowed": getattr(state, "escape_allowed", None),
            "switch_allowed": getattr(state, "switch_allowed", None)}


def strategy_summary(self):
    plan = self.data.get("plan") or {}
    goal = MAIN.get(self.owner.route.now, "Journey complete")
    clues = objective_clues(self.data["clues"], goal)
    action = self.owner.battle_executor.action
    intent = action.reason.split(":")[0] if action else self.owner.training.intent
    from .object_memory import obstruction_summary
    map_key = f'{self.map_key[0]:02X}:{self.map_key[1]:02X}' if self.map_key else None
    from .mine_guidance import mine_context
    mine = mine_context(getattr(self.observations, 'state', None), self.owner.route.now)
    next_label = ((self.data.get('blocker') or obstruction_summary(self.data, map_key)) if self.status == 'blocked' else
                  plan.get("explanation") or (self.target or {}).get("label", "Investigate local leads"))
    from .journey_hms import hm_journey
    hm_steps = hm_journey(getattr(self.observations, 'state', None), self.owner.route.now)
    active = hm_steps['active']
    if active and not self.target and not plan and self.status != 'blocked':
        next_label = active['label']
    from .journey_evidence import joined_pages
    clue = clues[-1] if clues else {}
    speaker = self.data['npcs'].get(clue.get('interaction'), {})
    known = joined_pages(speaker.get('pages', [])) or clue.get('text', 'No clues for this objective yet')
    from ..journey_checklist import journey_steps
    prerequisite = prerequisite_context(getattr(self.observations, 'state', None), self.owner.route.now)
    return {"hm_journey": hm_steps, "enabled": self.enabled, "status": self.status,
            "planner": self.label, "plan": plan,
            "last_response": self.data.get("last_response"),
            "accepted_target": (self.target or {}).get('label'),
            "selection_source": self.data.get('selection_source'),
            "plan_id": self.data.get('plan_id'), "plan_review": self.data.get('plan_review'),
            "error": getattr(self, "last_error", ""),
            "journey_steps": journey_steps(hm_steps, prerequisite),
            "lean_context": self.owner.memory.experience.lean_context(self.owner.route.now),
            "operator_guidance": self.owner.memory.experience.active_guide(self.owner.route.now),
            "goal": goal,
            "known": mine["known"] if mine else known,
            "next": mine["next"] if mine and not self.target and not active else next_label,
            "npcs": list(self.data["npcs"].values()), "events": self.data["events"][-8:],
            "stats": self.data["stats"], "rewards": self.owner.rewards.summary(),
            "playback": self.owner.playback.summary(),
            "intent": intent or "Continue journey",
            "journey_reward": (self.target or {}).get("journey_reward", 0)}
