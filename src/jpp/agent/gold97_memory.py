"""Small factual navigation memory, independent of the spoiler route guide."""

import json
import sqlite3


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
        self.world = json.loads(row[0]) if row else {"maps": {}, "facts": []}

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
        edge = [list(origin), direction]
        field = "edges" if destination != origin else "blocked"
        other = "blocked" if destination != origin else "edges"
        area[other] = [item for item in area[other] if item != edge]
        if edge not in area[field]:
            area[field].append(edge)
        if destination != origin:
            self.visited(key, destination)
        self.save()

    def remember(self, kind, value, map_key=""):
        fact = {"kind": kind, "value": str(value)[:180], "map": map_key}
        facts = self.world["facts"]
        if fact not in facts:
            facts.append(fact)
            self.world["facts"] = facts[-80:]
            self.save()

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
            return False
        self.world = json.loads(row[0])
        self.save()
        return True

    def reset(self):
        self.world = {"maps": {}, "facts": []}
        self.save()

    def close(self):
        self.db.close()
