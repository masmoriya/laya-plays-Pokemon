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
        from .navigation_memory import evidence_stamp
        item = {'target': target['id'], 'map': target.get('map', ''),
                'target_key': target_key(target),
                'evidence_stamp': evidence_stamp(self.memory, goal, target.get('map')),
                'goal': goal, 'reason': reason, 'label': target.get('label', target['id']),
                'retry_when': 'Relevant objective evidence changes, or manual Retry',
                'timestamp': time.time()}
        if target.get('reobserve_interaction'):
            item['reobserve_version'] = 1
        attempt_id = target_key(target) if target.get('reobserve_interaction') else target['id']
        self.db.execute('INSERT OR REPLACE INTO agent_attempts VALUES(?,?,?,?)',
                        (self.run_id, scope, attempt_id, json.dumps(item)))
        self.record('attempt_failed', **item)

    def failures(self, goal):
        from .navigation_memory import evidence_stamp
        rows = self.db.execute('SELECT scope,payload FROM agent_attempts WHERE run_id=?',
                               (self.run_id,))
        result = []
        for scope, payload in rows:
            item = json.loads(payload)
            if item.get('goal') != goal:
                continue
            if (item.get('reobserve_version') != 1
                    and item['reason'].startswith('Last-seen person')):
                continue  # Legacy arrivals failed before sprite/camera settling.
            if item['reason'].startswith('Last-seen person'):
                npc = self.memory.world.get('journey_strategy', {}).get('npcs', {}).get(item['target'], {})
                if npc.get('visible'):
                    continue  # Seeing the actual person makes this lead actionable again.
            stamp = item.get('evidence_stamp')
            if stamp is not None:
                if stamp != evidence_stamp(self.memory, goal, item.get('map')):
                    continue
            elif scope != prerequisites(self.memory, goal):
                continue  # Legacy checkpoint evidence remains scoped as recorded.
            result.append(item)
        return sorted(result, key=lambda item: item.get('timestamp', 0))

    def retry(self, goal):
        rows = self.db.execute('SELECT scope,target,payload FROM agent_attempts WHERE run_id=?',
                               (self.run_id,)).fetchall()
        for scope, target, payload in rows:
            if json.loads(payload).get('goal') == goal:
                self.db.execute('DELETE FROM agent_attempts WHERE run_id=? AND scope=? AND target=?',
                                (self.run_id, scope, target))
        for key in ('navigation_trace', 'transition_budget'):
            self.memory.world.pop(key, None)
        self.memory.save()
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

    def observe(self, state, *, overworld=False):
        current = observation(state)
        before = self.pending[1] if self.pending else None
        if overworld and not getattr(state, 'in_battle', False):
            current['screen'] = []
            if before is not None:
                before = {**before, 'screen': []}
        if self.pending and current != before:
            self.record('outcome', decision_id=self.pending[0], before=self.pending[1],
                        after=current, outcome=describe_change(before, current))
            self.pending = None
        return current

    def action(self, state, action, source, goal, model_input=None, *, selection_source=None, plan_id=None):
        current = observation(state)
        if self.pending:
            if self.pending[2] == action:
                return  # Held controls belong to the same attempt.
            self.interrupt('Superseded before an observed state change')
        identifier = self.record('action', action=action, source=source, goal=goal,
                                 before=current, model_input=model_input,
                                 selection_source=selection_source, plan_id=plan_id)
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
