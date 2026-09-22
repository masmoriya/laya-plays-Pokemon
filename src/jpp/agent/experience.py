"""Run-owned experience survives checkpoint rewinds; world facts do not."""

import hashlib
import json
import time


def prerequisites(memory, goal):
    world = memory.world
    clues = world.get('journey_strategy', {}).get('clues', [])
    evidence = {'goal': goal, 'completed': sorted(world.get('route', {}).get('completed', [])),
                'clues': sorted((c.get('map', ''), c['text']) for c in clues)}
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def target_key(target):
    return json.dumps([target.get('map'), target.get('kind'), target.get('cell'),
                       target.get('direction'), target.get('destination_key')], sort_keys=True)


class Experience:
    def __init__(self, memory):
        self.memory = memory
        self.db, self.run_id = memory.db, memory.run_id
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS agent_journal(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, timestamp REAL NOT NULL,
              kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS agent_journal_run ON agent_journal(run_id,id);
            CREATE TABLE IF NOT EXISTS agent_attempts(
              run_id TEXT NOT NULL, scope TEXT NOT NULL, target TEXT NOT NULL,
              payload TEXT NOT NULL, PRIMARY KEY(run_id,scope,target));
            CREATE TABLE IF NOT EXISTS agent_operator_messages(
              id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, timestamp REAL NOT NULL,
              kind TEXT NOT NULL, scope INTEGER, active INTEGER NOT NULL,
              text TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS agent_operator_run
              ON agent_operator_messages(run_id,id);
            CREATE TABLE IF NOT EXISTS agent_context_preferences(
              run_id TEXT NOT NULL, scope INTEGER NOT NULL, lean INTEGER NOT NULL,
              PRIMARY KEY(run_id,scope));
        ''')
        self.pending = None

    def record(self, kind, **payload):
        cursor = self.db.execute('INSERT INTO agent_journal(run_id,timestamp,kind,payload) VALUES(?,?,?,?)',
                                 (self.run_id, time.time(), kind, json.dumps(payload, default=str)))
        self.db.commit()
        return cursor.lastrowid

    def fail(self, goal, target, reason):
        scope = prerequisites(self.memory, goal)
        item = {'target': target['id'], 'map': target.get('map', ''),
                'target_key': target_key(target),
                'goal': goal, 'reason': reason, 'label': target.get('label', target['id']),
                'retry_when': 'Goal/dialogue evidence changes, or manual Retry',
                'timestamp': time.time()}
        self.db.execute('INSERT OR REPLACE INTO agent_attempts VALUES(?,?,?,?)',
                        (self.run_id, scope, target['id'], json.dumps(item)))
        self.record('attempt_failed', **item)

    def failures(self, goal):
        rows = self.db.execute('SELECT payload FROM agent_attempts WHERE run_id=? AND scope=?',
                               (self.run_id, prerequisites(self.memory, goal)))
        return [json.loads(row[0]) for row in rows]

    def retry(self, goal):
        self.db.execute('DELETE FROM agent_attempts WHERE run_id=? AND scope=?',
                        (self.run_id, prerequisites(self.memory, goal)))
        self.record('manual_retry', goal=goal)

    def recent(self, limit=100):
        rows = self.db.execute('SELECT id,timestamp,kind,payload FROM agent_journal '
                               'WHERE run_id=? ORDER BY id DESC LIMIT ?', (self.run_id, limit))
        return [{'id': i, 'timestamp': t, 'kind': k, **json.loads(p)} for i, t, k, p in rows]

    def add_operator_message(self, kind, text, scope=None):
        text = " ".join(str(text).split())[:500]
        if not text or kind not in {"guide", "remember"}:
            return None
        if kind == "guide":
            self.db.execute(
                "UPDATE agent_operator_messages SET active=0 "
                "WHERE run_id=? AND kind='guide' AND active=1", (self.run_id,)
            )
        cursor = self.db.execute(
            "INSERT INTO agent_operator_messages(run_id,timestamp,kind,scope,active,text) "
            "VALUES(?,?,?,?,1,?)", (self.run_id, time.time(), kind, scope, text)
        )
        self.db.commit()
        self.record("operator_" + kind, message_id=cursor.lastrowid,
                    scope=scope, text=text)
        return cursor.lastrowid

    def operator_messages(self, limit=20):
        rows = self.db.execute(
            "SELECT id,timestamp,kind,scope,active,text FROM agent_operator_messages "
            "WHERE run_id=? ORDER BY id DESC LIMIT ?", (self.run_id, limit)
        )
        return [{"id": i, "timestamp": timestamp, "kind": kind, "scope": scope,
                 "active": bool(active), "text": text}
                for i, timestamp, kind, scope, active, text in rows]

    def active_guide(self, scope):
        row = self.db.execute(
            "SELECT id,text FROM agent_operator_messages WHERE run_id=? "
            "AND kind='guide' AND active=1 AND scope=? ORDER BY id DESC LIMIT 1",
            (self.run_id, scope),
        ).fetchone()
        return {"id": row[0], "text": row[1]} if row else None

    def retire_guides(self, scope):
        self.db.execute(
            "UPDATE agent_operator_messages SET active=0 WHERE run_id=? "
            "AND kind='guide' AND active=1 AND scope<>?", (self.run_id, scope)
        )
        self.db.commit()

    def set_lean_context(self, scope, enabled):
        self.db.execute(
            "INSERT OR REPLACE INTO agent_context_preferences VALUES(?,?,?)",
            (self.run_id, int(scope or 0), int(bool(enabled))),
        )
        self.db.commit()
        self.record("context_mode", scope=scope,
                    mode="lean" if enabled else "standard")

    def lean_context(self, scope):
        row = self.db.execute(
            "SELECT lean FROM agent_context_preferences WHERE run_id=? AND scope=?",
            (self.run_id, int(scope or 0)),
        ).fetchone()
        return bool(row and row[0])

    def observe(self, state):
        current = observation(state)
        if self.pending and current != self.pending[1]:
            self.record('outcome', decision_id=self.pending[0], before=self.pending[1],
                        after=current, outcome=describe_change(self.pending[1], current))
            self.pending = None
        return current

    def action(self, state, action, source, goal, model_input=None):
        current = observation(state)
        if self.pending:
            if self.pending[2] == action:
                return  # Held controls belong to the same attempt.
            self.interrupt('Superseded before an observed state change')
        identifier = self.record('action', action=action, source=source, goal=goal,
                                 before=current, model_input=model_input)
        self.pending = identifier, current, action

    def interrupt(self, reason):
        if self.pending:
            self.record('outcome', decision_id=self.pending[0], outcome=reason,
                        before=self.pending[1])
            self.pending = None


def observation(state):
    battle = getattr(state, 'battle', None)
    foe = getattr(battle, 'opponent', None)
    return {'map': [getattr(state, 'map_group', None), getattr(state, 'map_number', None)],
            'position': [getattr(state, 'x', None), getattr(state, 'y', None)],
            'battle': getattr(battle, 'kind', None),
            'foe_hp': getattr(foe, 'hp', None),
            'party': [[m.species, getattr(m, 'hp', None), list(getattr(m, 'pp', ()))]
                      for m in getattr(state, 'party', ())],
            'screen': [' '.join(line.split()) for line in getattr(state, 'screen_lines', ())],
            'badges': list(getattr(state, 'badge_ids', ())) }


def describe_change(before, after):
    if before['map'] != after['map']:
        return f"Map transition {before['map']} to {after['map']}"
    if before['position'] != after['position']:
        return f"Moved {before['position']} to {after['position']}"
    if before['foe_hp'] != after['foe_hp']:
        return f"Opponent HP {before['foe_hp']} to {after['foe_hp']}"
    if before['party'] != after['party']:
        return 'Observed party HP, PP, or species change'
    if before['battle'] != after['battle']:
        return f"Battle state {before['battle']} to {after['battle']}"
    text = ' '.join(after['screen']).strip()
    return 'Screen changed: ' + text[-160:] if text else 'Display changed; no readable text'
