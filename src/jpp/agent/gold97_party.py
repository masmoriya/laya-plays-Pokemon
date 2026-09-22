"""Verified visible-menu party reorder; no raw memory writes."""
from .gold97_battle_executor import party_step


def select_label(state, label):
    cursor = state.screen_cursor
    column = cursor[0] + 1 if cursor and cursor[0] >= 7 else 0
    rows = [i for i, line in enumerate(state.screen_lines) if line[column:].strip().upper() == label]
    if len(rows) != 1 or cursor is None:
        return None
    if cursor[1] != rows[0]:
        return 'down' if cursor[1] < rows[0] else 'up'
    return 'a'


class PartyReorder:
    def __init__(self):
        self.target = None
        self.phase = None
        self.before = ()
        self.last = None
        self.repeats = 0
        self.confirmed = None
        self.error = ''
        self.attempted = set()

    def start(self, state, target):
        identities = tuple(m.identity for m in state.party)
        if (not state.mechanics_verified or target is None or target == 0 or
                not 0 <= target < len(identities) or None in identities or
                len(set(identities)) != len(identities)):
            return False
        if (identities, target) in self.attempted:
            return False
        self.attempted.add((identities, target))
        self.last, self.confirmed, self.repeats = None, None, 0
        self.target, self.before, self.phase = target, identities, 'open'
        self.error = ''
        return True

    def step(self, state, overworld):
        if self.phase is None:
            return None
        if state.in_battle:
            self.phase = None
            return None
        identities = tuple(m.identity for m in state.party)
        expected = list(self.before)
        expected[0], expected[self.target] = expected[self.target], expected[0]
        if identities == tuple(expected):
            self.phase = 'close'
        if self.phase == 'close':
            if overworld:
                self.phase = None
                return None
            return 'b'
        frame = (tuple(state.screen_lines), state.screen_cursor, identities)
        self.repeats = self.repeats + 1 if frame == self.last else 0
        self.last = frame
        if self.repeats >= 45:
            self.error, self.phase = 'Party reorder did not verify; leaving menu', 'close'
            return 'b'
        if frame == self.confirmed and self.repeats % 6:
            return None
        if overworld and self.phase in {'open', 'start'}:
            self.phase = 'start'
            return 'start'
        if self.phase == 'start':
            button = select_label(state, 'POK MON') or select_label(state, 'POKEMON')
            if button == 'a':
                self.phase = 'select'
        elif self.phase in {'select', 'destination'}:
            cursor = getattr(state, 'party_cursor', None)
            if cursor is None:
                return None
            button = party_step((1, cursor), self.target if self.phase == 'select' else 0)
            if button == 'a':
                self.phase = 'switch' if self.phase == 'select' else 'verify'
        elif self.phase == 'switch':
            button = select_label(state, 'SWITCH')
            if button == 'a':
                self.phase = 'destination'
        else:
            button = None
        if button == 'a':
            self.confirmed = frame
        return button
