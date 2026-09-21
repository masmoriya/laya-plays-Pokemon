"""Durable route and observed-map state, scoped to a run and checkpoint."""

import json
from dataclasses import replace
from pathlib import Path
import sqlite3
import time

from .route_progress import RouteProgress

MAP_VERSION = 3  # background decoded from VRAM, not lagging screen pixels


class Journey:
    def __init__(self, run_id, database="data/jev.sqlite"):
        self.run_id = run_id
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS journey_route(
                run_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS journey_tiles(
                run_id TEXT NOT NULL, map_key TEXT NOT NULL, x INTEGER NOT NULL,
                y INTEGER NOT NULL, tile_id INTEGER NOT NULL, rgba BLOB NOT NULL,
                PRIMARY KEY(run_id,map_key,x,y));
            CREATE TABLE IF NOT EXISTS journey_entities(
                run_id TEXT NOT NULL, map_key TEXT NOT NULL, entity_key TEXT NOT NULL,
                pixel_x INTEGER NOT NULL, pixel_y INTEGER NOT NULL, rgba BLOB NOT NULL,
                PRIMARY KEY(run_id,map_key,entity_key));
            CREATE TABLE IF NOT EXISTS journey_snapshots(
                path TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL,
                timestamp REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS journey_meta(
                run_id TEXT PRIMARY KEY, map_version INTEGER NOT NULL);
        """)
        row = self.db.execute("SELECT payload FROM journey_route WHERE run_id=?", (run_id,)).fetchone()
        self.route = RouteProgress.from_dict(json.loads(row[0]) if row else {})
        self.tiles = {}
        for map_key, x, y, tile_id, rgba in self.db.execute(
                "SELECT map_key,x,y,tile_id,rgba FROM journey_tiles WHERE run_id=?", (run_id,)):
            self.tiles.setdefault(map_key, {})[(x, y)] = (tile_id, rgba)
        self.entities = {}
        for map_key, entity_key, pixel_x, pixel_y, rgba in self.db.execute(
                "SELECT map_key,entity_key,pixel_x,pixel_y,rgba FROM journey_entities WHERE run_id=?", (run_id,)):
            if len(rgba) == 1024 and entity_key.startswith(("npc:v2:", "object:")):
                self.entities.setdefault(map_key, {})[entity_key] = (pixel_x, pixel_y, rgba)
        self._last_sample = None
        self.tile_revision = 0
        self.entity_revision = 0
        row = self.db.execute("SELECT map_version FROM journey_meta WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[0] != MAP_VERSION:
            if self.tiles or self.entities:
                self.record_checkpoint(f"archive:{run_id}:{time.time_ns()}:legacy-map",
                                       map_version=row[0] if row else 1)
                self.tiles = {}
                self.entities = {}
                self.db.execute("DELETE FROM journey_tiles WHERE run_id=?", (run_id,))
                self.db.execute("DELETE FROM journey_entities WHERE run_id=?", (run_id,))
            self.db.execute("INSERT OR REPLACE INTO journey_meta VALUES(?,?)", (run_id, MAP_VERSION))
            self.db.commit()

    def save_route(self):
        self.db.execute("INSERT OR REPLACE INTO journey_route VALUES(?,?)",
                        (self.run_id, json.dumps(self.route.to_dict())))
        self.db.commit()

    def observe_route(self, state):
        before = self.route.to_dict()
        self.route.observe(state)
        if self.route.to_dict() != before:
            self.save_route()

    def observe_tiles(self, state, samples, *, overworld=True):
        """Accept already-visible 8x8 background tiles, never fabricate hidden cells."""
        if not overworld or not samples or getattr(state, "in_battle", False):
            return 0
        x, y = getattr(state, "x", None), getattr(state, "y", None)
        group, number = getattr(state, "map_group", 0), getattr(state, "map_number", 0)
        if x is None or y is None or not group or not number:
            return 0
        key = f"{group:02X}:{number:02X}"
        bounds = (getattr(state, "map_width", 0) * 2, getattr(state, "map_height", 0) * 2)
        if not all(bounds) or (key, x, y) == self._last_sample:
            return 0
        self._last_sample = (key, x, y)
        area = self.tiles.setdefault(key, {})
        changed = 0
        for world_x, world_y, tile_id, rgba in samples:
            if not (0 <= world_x < bounds[0] and 0 <= world_y < bounds[1]):
                continue
            if len(rgba) != 256:  # 8x8 RGBA
                continue
            value = (int(tile_id), bytes(rgba))
            if area.get((world_x, world_y)) == value:
                continue
            area[(world_x, world_y)] = value
            self.db.execute("INSERT OR REPLACE INTO journey_tiles VALUES(?,?,?,?,?,?)",
                            (self.run_id, key, world_x, world_y, *value))
            changed += 1
        if changed:
            self.db.commit()
            self.tile_revision += 1
        return changed

    def observe_entities(self, state, entities, *, overworld=True):
        """Remember last-seen NPC sprite fragments without altering terrain."""
        if not overworld or not entities or getattr(state, "in_battle", False):
            return 0
        group, number = getattr(state, "map_group", 0), getattr(state, "map_number", 0)
        bounds = (getattr(state, "map_width", 0) * 16, getattr(state, "map_height", 0) * 16)
        if not group or not number or not all(bounds):
            return 0
        map_key = f"{group:02X}:{number:02X}"
        area = self.entities.setdefault(map_key, {})
        changed = 0
        for entity in entities:
            if getattr(entity, "map_key", None) != map_key:
                continue
            key = str(getattr(entity, "key", ""))
            pixel_x, pixel_y = int(getattr(entity, "pixel_x", -1)), int(getattr(entity, "pixel_y", -1))
            rgba = bytes(getattr(entity, "rgba", b""))
            if not key or not (0 <= pixel_x < bounds[0] and 0 <= pixel_y < bounds[1]) or len(rgba) != 1024:
                continue
            value = (pixel_x, pixel_y, rgba)
            if area.get(key) == value:
                continue
            area[key] = value
            self.db.execute("INSERT OR REPLACE INTO journey_entities VALUES(?,?,?,?,?,?)",
                            (self.run_id, map_key, key, *value))
            changed += 1
        if changed:
            self.db.commit()
            self.entity_revision += 1
        return changed

    def track_entities(self, state, detections):
        """Match changing OAM slots to persistent NPCs by map position."""
        if not detections or getattr(state, "in_battle", False):
            return ()
        map_key = f"{state.map_group:02X}:{state.map_number:02X}"
        remembered = self.entities.get(map_key, {})
        claimed = set()
        tracked = []
        for detection in detections:
            if detection.map_key != map_key:
                continue
            matches = sorted(
                (max(abs(x - detection.pixel_x), abs(y - detection.pixel_y)), key)
                for key, (x, y, _) in remembered.items() if key not in claimed
            )
            key = (detection.key if detection.key.startswith(("object:", "item:")) else
                   matches[0][1] if matches and matches[0][0] <= 24 else None)
            if key is None:
                base = f"npc:v2:{detection.pixel_x}:{detection.pixel_y}"
                key = base
                suffix = 2
                while key in remembered or key in claimed:
                    key = f"{base}:{suffix}"
                    suffix += 1
            current = replace(detection, key=key)
            if key in remembered and detection.parts < 4:
                old_x, old_y, old_rgba = remembered[key]
                if sum(a > 0 for a in old_rgba[3::4]) > sum(a > 0 for a in current.rgba[3::4]):
                    current = replace(current, pixel_x=old_x, pixel_y=old_y, rgba=old_rgba)
            claimed.add(key)
            tracked.append(current)
        self.observe_entities(state, tracked)
        return tuple(tracked)

    def snapshot(self, map_version=MAP_VERSION):
        return {"route": self.route.to_dict(), "map_version": map_version, "tiles": [
            (key, x, y, tile_id, rgba.hex())
            for key, cells in self.tiles.items()
            for (x, y), (tile_id, rgba) in cells.items()
        ], "entities": [
            (map_key, entity_key, pixel_x, pixel_y, rgba.hex())
            for map_key, entities in self.entities.items()
            for entity_key, (pixel_x, pixel_y, rgba) in entities.items()
        ]}

    def record_checkpoint(self, path, map_version=MAP_VERSION):
        self.db.execute("INSERT OR REPLACE INTO journey_snapshots VALUES(?,?,?,?)",
                        (str(path), self.run_id, json.dumps(self.snapshot(map_version)), time.time()))
        self.db.commit()

    def restore_checkpoint(self, path):
        row = self.db.execute("SELECT payload FROM journey_snapshots WHERE path=? AND run_id=?",
                              (str(path), self.run_id)).fetchone()
        if row is None:
            return False
        # Preserve the pre-restore view for later inspection, even after rewinding.
        archive = f"archive:{self.run_id}:{time.time_ns()}"
        self.record_checkpoint(archive)
        payload = json.loads(row[0])
        self.route = RouteProgress.from_dict(payload.get("route"))
        self.tiles = {}
        self.entities = {}
        with self.db:
            self.db.execute("DELETE FROM journey_tiles WHERE run_id=?", (self.run_id,))
            self.db.execute("DELETE FROM journey_entities WHERE run_id=?", (self.run_id,))
            for key, x, y, tile_id, rgba_hex in (
                    payload.get("tiles", ()) if payload.get("map_version") == MAP_VERSION else ()):
                rgba = bytes.fromhex(rgba_hex)
                self.tiles.setdefault(key, {})[(x, y)] = (tile_id, rgba)
                self.db.execute("INSERT INTO journey_tiles VALUES(?,?,?,?,?,?)",
                                (self.run_id, key, x, y, tile_id, rgba))
            for map_key, entity_key, pixel_x, pixel_y, rgba_hex in (
                    payload.get("entities", ()) if payload.get("map_version") == MAP_VERSION else ()):
                rgba = bytes.fromhex(rgba_hex)
                if len(rgba) != 1024 or not entity_key.startswith(("npc:v2:", "object:")):
                    continue
                self.entities.setdefault(map_key, {})[entity_key] = (pixel_x, pixel_y, rgba)
                self.db.execute("INSERT INTO journey_entities VALUES(?,?,?,?,?,?)",
                                (self.run_id, map_key, entity_key, pixel_x, pixel_y, rgba))
        self._last_sample = None
        self.tile_revision += 1
        self.entity_revision += 1
        self.save_route()
        return True

    def reset_view(self):
        self.record_checkpoint(f"archive:{self.run_id}:{time.time_ns()}")
        self.route = RouteProgress()
        self.tiles = {}
        self.entities = {}
        self._last_sample = None
        self.tile_revision += 1
        self.entity_revision += 1
        with self.db:
            self.db.execute("DELETE FROM journey_tiles WHERE run_id=?", (self.run_id,))
            self.db.execute("DELETE FROM journey_entities WHERE run_id=?", (self.run_id,))
        self.save_route()

    def close(self):
        self.db.close()
