"""PC transfers confirm a named menu action and then its roster delta."""
from collections import Counter
from .gold97_party import select_label


class PCTransfer:
    def __init__(self):
        self.plan = None
        self.phase = None
        self.before = ()
        self.boxes_before = ()
        self.last = None
        self.repeats = 0
        self.error = ''
        self.confirmed = None
        self.completed = False

    def start(self, state, plan):
        if not state.mechanics_verified or not state.storage_verified or plan is None:
            return False
        source = state.party if plan['kind'] == 'deposit' else state.box_roster
        matching = [m for m in source if m.identity == plan['identity']]
        if len(matching) != 1 or plan['kind'] not in {'deposit', 'withdraw'}:
            return False
        if plan['kind'] == 'deposit' and not any(m.hp > 0 and m.identity != plan['identity'] for m in state.party):
            return False
        if plan['kind'] == 'withdraw' and len(state.party) >= 6:
            return False
        all_ids = [m.identity for m in (*state.party, *state.box_roster)]
        if None in all_ids or len(all_ids) != len(set(all_ids)):
            return False
        if not isinstance(plan.get('box'), int) or not 0 <= plan['box'] < 14:
            return False
        if plan['kind'] == 'deposit' and sum(m.storage_box == plan['box'] for m in state.box_roster) >= 20:
            return False
        if plan['kind'] == 'withdraw' and matching[0].storage_box != plan['box']:
            return False
        self.plan, self.phase = dict(plan), 'access'
        self.before = tuple(m.identity for m in state.party)
        self.boxes_before = tuple(m.identity for m in state.box_roster)
        self.completed, self.error = False, ''
        self.last, self.confirmed, self.repeats = None, None, 0
        return True

    def step(self, state, overworld):
        if self.phase is None:
            return None
        if state.in_battle or not state.storage_verified:
            self.error, self.phase = 'PC state unavailable', 'close'
        party = tuple(m.identity for m in state.party)
        boxes = tuple(m.identity for m in state.box_roster)
        key = self.plan['identity']
        expected_party, expected_boxes = Counter(self.before), Counter(self.boxes_before)
        delta = -1 if self.plan['kind'] == 'deposit' else 1
        expected_party[key] += delta
        expected_boxes[key] -= delta
        expected = Counter(party) == +expected_party and Counter(boxes) == +expected_boxes
        if self.plan['kind'] == 'deposit':
            expected = expected and any(m.identity == key and m.storage_box == self.plan['box'] for m in state.box_roster)
        if expected:
            self.completed, self.phase = True, 'close'
        if self.phase == 'close':
            if overworld:
                self.phase = None
                return None
            return 'b'
        frame = (tuple(state.screen_lines), state.screen_cursor, party, boxes,
                 getattr(state, 'pc_selection', None))
        self.repeats = self.repeats + 1 if frame == self.last else 0
        self.last = frame
        if self.repeats >= 45:
            self.error, self.phase = 'PC transfer did not verify; leaving menu', 'close'
            return 'b'
        if frame == self.confirmed and self.repeats % 6:
            return None
        lines = state.screen_lines
        text = ' '.join(lines).upper()
        # Never confirm Release, and never guess at an unidentified yes/no prompt.
        if any(word in text for word in ('RELEASE ', 'RELEASE?', 'MAIL', 'BOX IS FULL')) and 'STATS' not in text:
            self.error, self.phase = 'PC transfer unavailable', 'close'
            return 'b'
        if self.phase == 'access':
            pc = next((line.strip().upper() for line in lines
                       if ('BILL' in line.upper() or 'SOMEONE' in line.upper()) and 'PC' in line.upper()), None)
            if pc:
                button = select_label(state, pc)
                if button == 'a': self.phase = 'operation'
            elif state.screen_cursor is None and any(word in text for word in ('TURNED ON', 'ACCESSED')):
                button = 'a'
            else:
                button = None
        elif self.phase == 'operation':
            if self.plan['box'] != state.current_box:
                button = select_label(state, 'CHANGE BOX')
                if button == 'a': self.phase = 'box'
            else:
                label = self.plan['kind'].upper()
                button = select_label(state, label + ' PKMN') or select_label(state, label)
                if button == 'a': self.phase = 'select'
            if 'WITHDRAW' not in text and any(word in text for word in ('ACCESSED', 'STORAGE', 'SYSTEM')):
                button = 'a'
        elif self.phase == 'box':
            # Only select an observed name from the cartridge's own box-name list.
            names = getattr(state, 'box_names', ())
            target = names[self.plan['box']] if self.plan['box'] < len(names) else None
            button = select_label(state, target.upper()) if target else None
            if button is None and target and state.screen_cursor is not None:
                visible = [i for i, name in enumerate(names)
                           if any(line.strip().upper() == name.upper() for line in lines)]
                if visible and self.plan['box'] > max(visible):
                    button = 'down'
                elif visible and self.plan['box'] < min(visible):
                    button = 'up'
            if button == 'a': self.phase = 'box_confirm'
        elif self.phase == 'box_confirm':
            if state.current_box == self.plan['box']:
                self.phase = 'box_close'
                return None
            button = select_label(state, 'SWITCH')
            if button is None and 'SAVE' in text:
                button = select_label(state, 'YES')
            if button is None and any(word in text for word in ('WHEN YOU CHANGE', 'BOX, DATA', 'WILL BE SAVED')):
                button = 'a'
            if 'SAVING' in text:
                button = None
            if 'SAVED THE GAME' in text:
                button = 'a'
        elif self.phase == 'box_close':
            if 'WITHDRAW' in text and 'CHANGE BOX' in text:
                self.phase = 'operation'
                return None
            button = 'b' if 'CHOOSE A BOX' in text else None
        elif self.phase == 'select':
            source = state.party if self.plan['kind'] == 'deposit' else [m for m in state.box_roster if m.storage_box == state.current_box]
            index = next((i for i,m in enumerate(source) if m.identity == key), None)
            cursor = getattr(state, 'pc_selection', None)
            if index is None or cursor is None or 'CANCEL' not in text:
                return None
            button = 'down' if cursor < index else 'up' if cursor > index else 'a'
            if button == 'a': self.phase = 'confirm'
        elif self.phase == 'confirm':
            button = select_label(state, self.plan['kind'].upper())
            if button == 'a': self.phase = 'verify'
        else:
            button = None
        if button == 'a': self.confirmed = frame
        return button
