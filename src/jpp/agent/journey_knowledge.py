"""Checkpoint-owned observations and interactions, independent of model availability."""

from .gold97_items import item_cell
from .object_memory import classify, close_interaction, manual_target, evidence_key, attempt
from .journey_evidence import dialogue_text, migrate


def knowledge(memory, enabled=True):
    data = memory.world.setdefault("journey_strategy", {
        "enabled": enabled, "npcs": {}, "clues": [], "connections": [],
        "events": [], "stats": {}, "plan": None, "route_maps": {},
    })
    migrate(data)
    data.setdefault("route_maps", {})
    for npc in data["npcs"].values():
        classify(npc)
    return data


def record(memory, kind, detail, **extra):
    data = knowledge(memory)
    mode = "luna_on" if data["enabled"] else "luna_off"
    data["events"].append({"kind": kind, "detail": detail, "mode": mode, **extra})
    data["events"] = data["events"][-100:]
    stats = data["stats"].setdefault(mode, {})
    stats[kind] = stats.get(kind, 0) + 1
    memory.save()
    memory.experience.record(kind, detail=detail, mode=mode, **extra)


class JourneyKnowledge:
    def __init__(self, memory):
        self.memory = memory
        self.pending = None
        self.last_map = None
        self.last_position = None
        self.text = ""
        self.stable = 0
        self.revision = 0
        self.last_direction = ""
        self.last_exits = ()
        self.after_battle = False
        self.battle_interaction = None

    @property
    def data(self):
        return knowledge(self.memory)

    def observe(self, state, entities, *, overworld, milestone, prompt_visible=None):
        self.state = state
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        changed = False
        if not state.in_battle and self.battle_interaction:
            npc = self.data["npcs"].get(self.battle_interaction)
            result = getattr(state, "battle_result", None)
            if npc and result is not None and result & ~0xC0 == 0:
                npc.update(status="talked", outcome="defeated")
                npc["completed_milestone"] = milestone
                record(self.memory, "conversation_battle_won", npc["id"])
                changed = True
            self.battle_interaction = None
        if state.in_battle:
            # Preserve stable pre-battle dialogue; starting is not winning.
            if self.pending and not self.after_battle:
                if self.stable >= 2 and self.text:
                    changed |= self.capture(self.text, key)
                self.battle_interaction = self.pending["id"]
                record(self.memory, "conversation_battle", self.pending["id"])
            self.pending = None
            self.after_battle = True
            self.text, self.stable = '', 0
        if overworld and not state.in_battle:
            self.after_battle = False
        same_map_warp = (self.last_map == key and self.last_position is not None
                         and abs(state.x-self.last_position[0]) + abs(state.y-self.last_position[1]) > 1
                         and any(list(exit[:2]) == self.last_position for exit in self.last_exits)) if overworld else False
        if overworld and self.last_map and (self.last_map != key or same_map_warp):
            direction = next((direction for x, y, direction, group, number in self.last_exits
                              if [x, y] == self.last_position
                              and ((group, number) == (state.map_group, state.map_number)
                                   or (group, number) == (0, 0))),
                             self.last_direction)
            connection = {"from": self.last_map, "at": self.last_position,
                          "to": key, "arrival": [state.x, state.y],
                          "direction": direction}
            if connection not in self.data["connections"]:
                self.data["connections"].append(connection)
                changed = True
            self.last_direction = ""
        if overworld and not state.in_battle:
            for npc in self.data["npcs"].values():
                npc["visible"] = False
            if self.last_map == key and self.last_position:
                from .navigation_trace import record_step
                record_step(self.memory, key, self.last_position, (state.x, state.y))
                delta = state.x - self.last_position[0], state.y - self.last_position[1]
                directions = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}
                self.last_direction = directions.get(delta, self.last_direction)
            self.last_map, self.last_position = key, [state.x, state.y]
            self.last_exits = getattr(state, "map_exits", ())
            destinations = sorted({f'{group:02X}:{number:02X}'
                                   for _, _, _, group, number in self.last_exits})
            exits = self.data.setdefault('map_exits', {})
            if destinations and exits.get(key) != destinations:
                exits[key] = destinations
                changed = True
            claimed = set()
            for entity in entities:
                cell = item_cell(entity)
                if cell is None or getattr(entity, "key", "") == "player":
                    continue
                if getattr(entity, "map_key", key) != key:
                    continue
                identity = str(getattr(entity, "key", ""))
                # Raw OAM slots are temporary; match nearby prior observations.
                if not identity or identity.startswith("oam:"):
                    matches = [(abs(n["cell"][0] - cell[0]) + abs(n["cell"][1] - cell[1]), i)
                               for i, n in self.data["npcs"].items()
                               if n["map"] == key and i not in claimed
                               and "observed_from" not in n]
                    near = min(matches, default=(99, ""))
                    identity = near[1].split("/", 1)[-1] if near[0] <= 1 else f"sprite:{cell}"
                identifier = f"{key}/{identity}"
                claimed.add(identifier)
                npc = self.data["npcs"].get(identifier)
                if npc is None:
                    npc = {"id": identifier, "map": key, "cell": list(cell),
                           "status": "pending", "attempts": 0, "milestone": milestone,
                           "pages": []}
                    self.data["npcs"][identifier] = npc
                    changed = True
                classify(npc)
                if getattr(entity, 'kind', '') in {'item', 'obstacle', 'npc'}:
                    npc['category'] = entity.kind
                npc["observed"] = True
                npc["visible"] = True
                if npc["cell"] != list(cell):
                    if npc.get('category') == 'obstacle' and npc.get('outcome') == 'unresolved':
                        npc.update(outcome='moved', status='resolved', last_result='Observed object movement')
                        self.memory.clear_transient_blocks(key)
                        changed = True
                    npc["cell"] = list(cell)
                if npc["milestone"] != milestone:
                    npc["milestone"] = milestone
                    self.memory.save()
        lines = getattr(state, "screen_lines", ())
        dialogue_lines = lines[12:] if len(lines) >= 18 else lines
        text = " ".join(line.strip() for line in dialogue_lines if line.strip())[:1500]
        # A restored/manual interaction may have no planner-owned target. Keep
        # the observed location without guessing which adjacent object spoke.
        if (not self.pending and not overworld and not state.in_battle
                and not self.after_battle and prompt_visible is True
                and getattr(state, "screen_cursor", None) is None
                and dialogue_text(text) and state.x is not None and state.y is not None):
            identifier = manual_target(self.data, state, key)
            self.data["npcs"].setdefault(identifier, {
                "id": identifier, "map": key, "cell": [state.x, state.y],
                "observed_from": [state.x, state.y], "visible": False,
                "status": "pending", "attempts": 0, "milestone": milestone, "pages": [],
            })
            self.interacted(identifier)
        if (self.pending and not self.after_battle and not overworld
                and not state.in_battle and prompt_visible is not False and dialogue_text(text)):
            if text != self.text and self.stable >= 2 and not text.startswith(self.text):
                changed |= self.capture(self.text, key)
            self.stable = self.stable + 1 if text == self.text else 0
            self.text = text
            if self.stable >= 12:
                changed |= self.capture(text, key)
        if self.pending and overworld and not state.in_battle:
            if self.stable >= 2 and self.text:
                changed |= self.capture(self.text, key)
            npc = self.data["npcs"].get(self.pending["id"])
            self.pending["ticks"] += 1
            if self.pending["saw_text"]:
                close_interaction(npc)
                npc["completed_milestone"] = milestone
                record(self.memory, "conversation", npc["id"])
                self.pending = None
                self.text, self.stable = "", 0
                changed = True
            elif self.pending["ticks"] > 90:
                npc["status"] = "pending" if npc["attempts"] < 2 else "deferred"
                record(self.memory, "interaction_failed", npc["id"])
                self.pending = None
                changed = True
        if changed:
            self.revision += 1
            self.memory.save()
        return changed

    def capture(self, text, key):
        if not self.pending or self.after_battle or not dialogue_text(text):
            return False
        updated = False
        if self.pending:
            npc = self.data["npcs"].get(self.pending["id"])
            if npc and text not in npc["pages"]:
                npc["pages"].append(text)
                npc["pages"] = npc["pages"][-12:]
                updated = True
            self.pending["saw_text"] = True
        if any(c["text"] == text and c["map"] == key for c in self.data["clues"]):
            return updated
        existing = [int(c['id'].split(':')[1]) for c in self.data['clues']
                    if c.get('id', '').startswith('clue:') and c['id'].split(':')[1].isdigit()]
        self.data['next_clue_id'] = max(self.data.get('next_clue_id', 0), max(existing, default=-1) + 1)
        self.data["clues"].append({"id": f"clue:{self.data.setdefault('next_clue_id', len(self.data['clues']))}",
                                  "text": text, "map": key, "source": "dialogue",
                                  "interaction": self.pending["id"],
                                  "cell": list(npc["cell"]) if npc else None})
        self.data["next_clue_id"] += 1
        self.memory.experience.record('clue', clue=self.data['clues'][-1])
        return True

    def interacted(self, identifier):
        npc = self.data["npcs"].get(identifier)
        if npc and not self.pending:
            self.text, self.stable = "", 0
            npc["attempts"] += 1
            state = getattr(self, 'state', None)
            attempt(npc, evidence_key(state, npc, self.memory))
            self.pending = {"id": identifier, "ticks": 0, "saw_text": False}
            self.memory.save()
