"""Teach an owned HM through visible menus and verify the party move afterward."""
import re
from types import SimpleNamespace

from .gold97_choices import answer_button, choice_rows
from .gold97_learning import learning_menu_step
from .gold97_party import select_label
from .gold97_battle_executor import party_step
from .journey_hms import hm_journey
from ..field_moves import normalize


class HMTeaching:
    def __init__(self):
        self.phase = None
        self.error = ''
        self.plan = None

    def start(self, state, milestone):
        focus = hm_journey(state, milestone)['active']
        if not focus or focus['action'] != 'teach':
            return False
        self.plan = focus['teaching']
        if (self.plan['identity'] is None or
                sum(mon.identity == self.plan['identity'] for mon in state.party) != 1):
            return False
        self.phase, self.error = 'open', ''
        self.ticks, self.repeats, self.pockets = 0, 0, 0
        self.last = self.confirmed = None
        return True

    def step(self, state, overworld):
        if self.phase is None:
            return None
        if state.in_battle:
            self.phase = None
            return None
        self.ticks += 1
        plan = self.plan
        mon = next((mon for mon in state.party if mon.identity == plan['identity']), None)
        learned = mon is not None and normalize(plan['move']) in {normalize(m) for m in mon.moves}
        if learned:
            self.phase = 'close'
        elif mon is None or tuple(mon.moves) != plan['before']:
            self.error, self.phase = 'Party changed during HM teaching', 'close'
        frame = (tuple(state.screen_lines), state.screen_cursor, getattr(state, 'party_cursor', None))
        self.repeats = self.repeats + 1 if frame == self.last else 0
        self.last = frame
        if self.ticks > 120 or self.repeats > 16:
            self.error, self.phase = f"Could not verify teaching {plan['move']}", 'close'
        if self.phase == 'close':
            if overworld or self.ticks > 140:
                self.phase = None
                return None
            return 'b'
        # One confirmation per visible page; do not double-select a stale menu.
        if frame == self.confirmed:
            return None
        button = self._menu_step(state, overworld, mon)
        if button == 'a':
            self.confirmed = frame
        return button

    def _menu_step(self, state, overworld, mon):
        plan = self.plan
        if self.phase == 'open':
            if overworld:
                self.phase = 'pack'
                return 'start'
            return None
        if self.phase == 'pack':
            button = select_label(state, 'PACK')
            if button == 'a':
                self.phase = 'pocket'
            return button
        if self.phase == 'pocket':
            rows = [(i, line.strip().upper()) for i, line in enumerate(state.screen_lines)]
            target = next((i for i, line in rows
                           if re.fullmatch(rf"H0?{plan['number']}\s+{re.escape(plan['move'].upper())}", line)), None)
            cursor = state.screen_cursor
            if cursor is None:
                return None
            if target is not None:
                if cursor[1] != target:
                    return 'down' if cursor[1] < target else 'up'
                self.phase = 'use'
                return 'a'
            if any(re.match(r'^(?:H\d|\d{1,2})\s+[A-Z]', line) for _, line in rows):
                return 'down'  # Scroll the verified TM/HM list to the owned HM.
            if self.pockets >= 4:
                self.error, self.phase = 'TM/HM pocket was not readable', 'close'
                return 'b'
            self.pockets += 1
            return 'right'
        if self.phase == 'use':
            button = select_label(state, 'USE')
            if button == 'a':
                self.phase = 'offer'
            return button
        if self.phase == 'offer':
            if choice_rows(state):
                # The contained move must match before accepting the offer.
                offer = ' '.join(' '.join(state.screen_lines[12:]).upper().split())
                if f"TEACH {plan['move'].upper()}" not in offer:
                    self.error, self.phase = 'HM offer did not match the selected move', 'close'
                    return 'b'
                button = answer_button(state, 'yes')
                if button == 'a':
                    self.phase = 'party'
                return button
            return 'a' if any(line.strip() for line in state.screen_lines[12:]) else None
        if self.phase == 'party':
            cursor = getattr(state, 'party_cursor', None)
            if cursor is None:
                return None
            slot = next(i for i, member in enumerate(state.party) if member.identity == plan['identity'])
            button = party_step((1, cursor), slot)
            if button == 'a':
                self.phase = 'learn'
            return button
        if self.phase == 'learn':
            from .gold97_learning import _contains_move
            visible_moves = sum(any(_contains_move(line, move) for line in state.screen_lines)
                                for move in mon.moves)
            if not choice_rows(state) and visible_moves < 2:
                return 'a' if any(line.strip() for line in state.screen_lines[12:]) else None
            # Restrict move deletion to the chosen Pokemon, preserving other HMs.
            learning_state = SimpleNamespace(party=(mon,), screen_lines=state.screen_lines,
                                             screen_cursor=state.screen_cursor, battle_menu_kind=None)
            result = learning_menu_step(learning_state, plan['move'])
            if result is not None:
                button, detail = result
                if button is None:
                    self.error, self.phase = detail, 'close'
                    return 'b'
                return None if button == 'wait' else button
            return 'a' if any(line.strip() for line in state.screen_lines[12:]) else None
        return None
