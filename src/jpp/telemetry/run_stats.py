"""Durable run identity, statistics, event log, memories, and checkpoints."""

import json
from pathlib import Path
import sqlite3
import time

from .events import Event


class RunStore:
    def __init__(self, path="data/jev.sqlite", run_id="run-001"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.run_id = run_id
        self._schema()
        self.db.execute(
            "INSERT OR IGNORE INTO runs(run_id,started_at,last_seen) VALUES(?,?,?)",
            (run_id, time.time(), time.time()),
        )
        self.db.commit()

    def _schema(self):
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs(
              run_id TEXT PRIMARY KEY, started_at REAL NOT NULL, last_seen REAL NOT NULL,
              stats_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, type TEXT NOT NULL,
              payload_json TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
              importance REAL NOT NULL, text TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS objectives(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, objective TEXT NOT NULL,
              status TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoints(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, path TEXT NOT NULL,
              metadata_json TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL,
              payload_json TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS badges(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, badge TEXT NOT NULL,
              timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pokemon(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, species TEXT NOT NULL,
              payload_json TEXT NOT NULL, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stream_sessions(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, started_at REAL NOT NULL,
              ended_at REAL
            );
            CREATE TABLE IF NOT EXISTS recoveries(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL,
              payload_json TEXT NOT NULL, timestamp REAL NOT NULL
            );
            """
        )

    def emit(self, event: Event):
        self.db.execute(
            "INSERT INTO events(run_id,type,payload_json,timestamp) VALUES(?,?,?,?)",
            (self.run_id, str(event.type), json.dumps(event.payload), event.timestamp),
        )
        self.db.execute("UPDATE runs SET last_seen=? WHERE run_id=?", (time.time(), self.run_id))
        self.db.commit()

    def remember(self, kind, text, importance=0.5):
        self.db.execute(
            "INSERT INTO memories(run_id,kind,importance,text,timestamp) VALUES(?,?,?,?,?)",
            (self.run_id, kind, float(importance), text, time.time()),
        )
        self.db.commit()

    def relevant_memories(self, kind=None, limit=8):
        query = "SELECT kind,importance,text,timestamp FROM memories WHERE run_id=?"
        args = [self.run_id]
        if kind:
            query += " AND kind=?"
            args.append(kind)
        query += " ORDER BY importance DESC,timestamp DESC LIMIT ?"
        args.append(limit)
        return [dict(row) for row in self.db.execute(query, args)]

    def set_stats(self, **values):
        row = self.db.execute("SELECT stats_json FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
        stats = json.loads(row[0]) if row else {}
        stats.update(values)
        self.db.execute("UPDATE runs SET stats_json=?,last_seen=? WHERE run_id=?", (json.dumps(stats), time.time(), self.run_id))
        self.db.commit()
        return stats

    def stats(self):
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
        if not row:
            return {}
        return {"run_id": self.run_id, "started_at": row["started_at"], "last_seen": row["last_seen"], **json.loads(row["stats_json"])}

    def add_checkpoint(self, path, metadata):
        self.db.execute(
            "INSERT INTO checkpoints(run_id,path,metadata_json,timestamp) VALUES(?,?,?,?)",
            (self.run_id, str(path), json.dumps(metadata), time.time()),
        )
        self.db.commit()

    def latest_checkpoint(self):
        row = self.db.execute("SELECT * FROM checkpoints WHERE run_id=? ORDER BY timestamp DESC LIMIT 1", (self.run_id,)).fetchone()
        return {**dict(row), "metadata": json.loads(row["metadata_json"])} if row else None

    def checkpoint_metadata(self, path):
        row = self.db.execute(
            "SELECT metadata_json FROM checkpoints WHERE run_id=? AND path=? ORDER BY id DESC LIMIT 1",
            (self.run_id, str(path)),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def close(self):
        self.db.close()
