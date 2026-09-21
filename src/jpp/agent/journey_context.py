"""Compact planner context and live journey summaries."""

from ..route_progress import MAIN


def strategy_context(self, state):
    goal = MAIN.get(self.owner.route.now, "Journey complete")
    words = {word.strip(".,").lower() for word in goal.split() if len(word) > 3}
    clues = self.data["clues"]
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
                   'connections': snapshot.connections}
                  if snapshot else None)
    goal = MAIN.get(self.owner.route.now, "Journey complete")
    directive = (
        f"A verified Journey milestone is worth "
        f"{self.owner.rewards.weights['milestone']} reward points. Choose the highest "
        "Journey-reward candidate unless current evidence makes it unsafe or unreachable. "
        "Do not trade milestone progress for unrelated NPCs, buildings, services, "
        "optional rooms, training, or exhaustive map coverage."
    )
    return {"navigation": navigation, "goal": goal, "directive": directive,
            "map": state.area_name,
            "candidates": (self.payload or {}).get("candidates", []),
            "clues": relevant[-20:] + clues[-20:],
            "interactions": [{**npc, "pages": npc["pages"][-2:]}
                             for npc in self.data["npcs"].values()],
            "team": {"training": self.owner.training.summary(state, self.owner.rewards.weights), "party": [{"species": m.species, "level": m.level, "hp": m.hp} for m in getattr(state, "party", ())],
                     "rewards": self.owner.rewards.summary()},
            "connections": self.data["connections"], "recent": self.data["events"][-12:],
            "questions": ["Which candidate has the strongest verified Journey reward?",
                          "What observable result proves progress toward this milestone?"]}


def strategy_summary(self):
    plan = self.data.get("plan") or {}
    action = self.owner.battle_executor.action
    intent = action.reason.split(":")[0] if action else self.owner.training.intent
    return {"enabled": self.enabled, "status": self.status,
            "goal": MAIN.get(self.owner.route.now, "Journey complete"),
            "known": self.data["clues"][-1]["text"] if self.data["clues"] else "No dialogue clues yet",
            "next": plan.get("explanation") or (self.target or {}).get("label", "Investigate local leads"),
            "npcs": list(self.data["npcs"].values()), "events": self.data["events"][-8:],
            "stats": self.data["stats"], "rewards": self.owner.rewards.summary(),
            "playback": self.owner.playback.summary(),
            "intent": intent or "Continue journey",
            "journey_reward": (self.target or {}).get("journey_reward", 0)}
