"""Small factual navigation memory, independent of the spoiler route guide."""

import json
import sqlite3
import time
from pathlib import Path


NAVIGATION_VERSION = 5


def _migrate_world(world):
    """Drop movement evidence recorded before coordinate validation."""
    if not isinstance(world, dict):
        world = {}
    world.setdefault("maps", {})
    world.setdefault("facts", [])
    if int(world.get("navigation_version", 1) or 1) < NAVIGATION_VERSION:
        previous = int(world.get('navigation_version', 1) or 1)
        for area in world["maps"].values():
            if isinstance(area, dict):
                if area.get('blocked'):
                    area['legacy_blocked'] = area['blocked']
                area["blocked"] = []
                if previous < 3:
                    area["edges"] = []
        world["navigation_version"] = NAVIGATION_VERSION
    return world


class Gold97Memory:
    def __init__(self, run_id, database="data/jev.sqlite"):
        self.run_id = run_id
        self.db = sqlite3.connect(database)
        self.db.execute("CREATE TABLE IF NOT EXISTS agent_world("
                        "run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS agent_world_checkpoints("
                        "run_id TEXT NOT NULL, path TEXT NOT NULL, payload TEXT NOT NULL,"
                        "PRIMARY KEY(run_id,path))")
        row = self.db.execute("SELECT payload FROM agent_world WHERE run_id=?", (run_id,)).fetchone()
        self.world = _migrate_world(json.loads(row[0]) if row else {
            "maps": {}, "facts": [], "navigation_version": NAVIGATION_VERSION,
        })
        self.save()
        from .experience import Experience
        self.experience = Experience(self)

    def map(self, key):
        return self.world["maps"].setdefault(key, {"visited": [], "edges": [], "blocked": []})

    def visited(self, key, position):
        area = self.map(key)
        point = list(position)
        if point not in area["visited"]:
            area["visited"].append(point)
            self.save()

    def move_result(self, key, origin, direction, destination):
        area = self.map(key)
        delta = (destination[0] - origin[0], destination[1] - origin[1])
        steps = {"up": (0, -1), "down": (0, 1),
                 "left": (-1, 0), "right": (1, 0)}
        if destination != origin and delta != steps.get(direction):
            # Drift, scripted movement and warps do not prove the requested edge.
            self.visited(key, destination)
            return
        edge = [list(origin), direction]
        field = "edges" if destination != origin else "blocked"
        other = "blocked" if destination != origin else "edges"
        stamp = json.dumps(edge)
        times = area.setdefault("blocked_at", {})
        if destination == origin:
            times[stamp] = time.time()
        else:
            times.pop(stamp, None)
        area[other] = [item for item in area[other] if item != edge]
        if edge not in area[field]:
            area[field].append(edge)
        if destination != origin:
            self.visited(key, destination)
        self.save()

    def clear_transient_blocks(self, key):
        """Recheck movement after scripts and battles can move map objects."""
        area = self.map(key)
        if area["blocked"]:
            area["blocked"] = []
            area["blocked_at"] = {}
            self.save()

    def expire_blocked(self, key, now=None):
        """A failed step may be a sprite or animation, not a permanent wall."""
        area = self.map(key)
        now = time.time() if now is None else now
        times = area.setdefault("blocked_at", {})
        expired = {stamp for stamp, when in times.items() if now - when >= 30}
        if expired:
            area["blocked"] = [edge for edge in area["blocked"]
                               if json.dumps(edge) not in expired]
            for stamp in expired:
                times.pop(stamp, None)
            self.save()

    def clear_blocked_at(self, key, position):
        """Discard edges that may have been blocked by a moving battle NPC."""
        area = self.map(key)
        before = len(area["blocked"])
        area["blocked"] = [edge for edge in area["blocked"]
                           if edge[0] != list(position)]
        if len(area["blocked"]) != before:
            self.save()

    def remember(self, kind, value, map_key=""):
        fact = {"kind": kind, "value": str(value)[:180], "map": map_key}
        facts = self.world["facts"]
        if fact not in facts:
            facts.append(fact)
            self.world["facts"] = facts[-80:]
            self.save()
            self.experience.record('fact', fact=fact)

    def relevant(self, map_key):
        local = [fact for fact in self.world["facts"] if fact["map"] == map_key]
        global_facts = [fact for fact in self.world["facts"] if not fact["map"]]
        return (local[-8:] + global_facts[-4:])[-10:]

    def save(self):
        self.db.execute("INSERT OR REPLACE INTO agent_world VALUES(?,?)",
                        (self.run_id, json.dumps(self.world)))
        self.db.commit()

    def checkpoint(self, path):
        self.db.execute("INSERT OR REPLACE INTO agent_world_checkpoints VALUES(?,?,?)",
                        (self.run_id, str(path), json.dumps(self.world)))
        self.db.commit()

    def restore(self, path):
        row = self.db.execute("SELECT payload FROM agent_world_checkpoints WHERE run_id=? AND path=?",
                              (self.run_id, str(path))).fetchone()
        if row is None:
            # The same explicit checkpoint may be opened with an absolute path
            # or a different run label. Reuse only its exact recorded payload;
            # never substitute the newest state from another run.
            resolved = Path(path).resolve()
            matches = [(run, saved) for run, saved in self.db.execute(
                'SELECT run_id,path FROM agent_world_checkpoints')
                if Path(saved).resolve() == resolved]
            own = [(run, saved) for run, saved in matches if run == self.run_id]
            payloads = [self.db.execute(
                'SELECT payload FROM agent_world_checkpoints WHERE run_id=? AND path=?', pair).fetchone()[0]
                for pair in (own or matches)]
            if not payloads or len(set(payloads)) != 1:
                return False
            row = (payloads[0],)
        self.experience.interrupt('Checkpoint restored; prior action outcome is unknown')
        enabled = self.world.get("journey_strategy", {}).get("enabled")
        self.world = _migrate_world(json.loads(row[0]))
        if enabled is not None:
            from .journey_knowledge import knowledge
            knowledge(self)["enabled"] = enabled
        self.save()
        self.experience.record('restore', checkpoint=str(path))
        return True

    def reset(self):
        self.experience.interrupt('World reset; prior action outcome is unknown')
        enabled = self.world.get("journey_strategy", {}).get("enabled")
        self.world = {"maps": {}, "facts": [], "navigation_version": NAVIGATION_VERSION}
        if enabled is not None:
            from .journey_knowledge import knowledge
            knowledge(self)["enabled"] = enabled
        self.save()

    def close(self):
        self.db.close()
