"""Persist user intent independently of temporary executor/provider state."""
from time import monotonic


class Playback:
    def __init__(self, memory):
        self.memory = memory
        self.db = memory.db
        self.db.execute('CREATE TABLE IF NOT EXISTS agent_playback(run_id TEXT PRIMARY KEY, requested INTEGER NOT NULL)')
        row = self.db.execute('SELECT requested FROM agent_playback WHERE run_id=?', (memory.run_id,)).fetchone()
        self.requested = bool(row and row[0])
        self.status = 'recovering' if self.requested else 'manually paused'
        self.reason = ''
        self.attempts = 0
        self.retry_at = 0

    def request(self, value):
        self.requested = bool(value)
        self.status = 'recovering' if value else 'manually paused'
        self.reason = ''
        self.db.execute('INSERT OR REPLACE INTO agent_playback VALUES(?,?)',
                        (self.memory.run_id, int(value)))
        self.db.commit()

    def waiting(self, reason):
        if self.status != 'waiting for provider':
            self.attempts += 1
            self.retry_at = monotonic() + min(30, 2 ** min(self.attempts, 5))
        self.status, self.reason = 'waiting for provider', reason

    def ready(self):
        self.status, self.reason = 'playing', ''
        self.attempts = 0

    def blocked(self, reason):
        self.status, self.reason = 'blocked', reason

    def summary(self):
        return {'requested': self.requested,
                'status': self.status if self.requested else 'manually paused',
                'reason': self.reason}
