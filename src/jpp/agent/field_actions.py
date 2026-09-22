"""Bounded field-move experiments using observed party menus and dialogue."""
from .gold97_party import select_label
from .gold97_battle_executor import party_step
from ..field_moves import field_ready
from .object_memory import classify, normalized, evidence_key, eligible, attempt
from .gold97_choices import answer_button, choice_rows

FIELD_MOVES = {'CUT', 'SURF', 'STRENGTH', 'FLASH', 'WHIRLPOOL', 'WATERFALL', 'ROCK SMASH'}


def strength_push(state, npc, memory):
    text = normalized(' '.join(npc.get('pages', ())))
    return (getattr(state, 'strength_active', False)
            and any(word in text for word in ('MOVE', 'HEAVY', 'BOULDER'))
            and eligible(npc, evidence_key(state, npc, memory), 'push'))


def record_push(state, npc, memory, direction):
    if getattr(state, 'player_facing', None) == direction and strength_push(state, npc, memory):
        attempt(npc, evidence_key(state, npc, memory), 'push')


def field_confirmation(state):
    """Accept only an explicit field-use offer for a learned, unlocked move."""
    if not choice_rows(state):
        return None
    text = normalized(' '.join(getattr(state, 'screen_lines', ())))
    for move in FIELD_MOVES:
        if (f'USE {move}' in text and 'WANT' in text and field_ready(state, move)
                and any(move in {normalized(m).replace('_', ' ') for m in mon.moves}
                        for mon in getattr(state, 'party', ()))):
            return answer_button(state, 'yes')
    return None


def experiments(state, npc, memory=None):
    text = normalized(' '.join(npc.get('pages', ())))
    # This is a hypothesis from dialogue, never a claim about cartridge prerequisites.
    names = {'STRENGTH'} if any(w in text for w in ('MOVE', 'HEAVY', 'BOULDER')) else FIELD_MOVES
    if getattr(state, 'strength_active', False):
        names = names - {'STRENGTH'}
    context = evidence_key(state, npc, memory)
    return [(slot, normalized(move).replace('_', ' '))
            for slot, mon in enumerate(getattr(state, 'party', ()))
            for move in getattr(mon, 'moves', ())
            if normalized(move).replace('_', ' ') in names and field_ready(state, move)
            and eligible(npc, context, f'field:{slot}:{normalized(move).replace("_", " ")}')]


class FieldAction:
    def __init__(self):
        self.phase = None
        self.error = ''

    def start(self, state, npc, memory):
        choices = experiments(state, npc, memory)
        if not choices:
            npc['last_result'] = 'No untried relevant field move in the observed party'
            memory.save()
            return False
        self.slot, self.move = choices[0]
        self.npc, self.memory = npc, memory
        self.direction = getattr(state, 'player_facing', None)
        attempt(npc, evidence_key(state, npc, memory), f'field:{self.slot}:{self.move}')
        self.phase, self.ticks, self.last, self.repeats = 'start', 0, None, 0
        self.error = ''
        memory.experience.record('field_attempt', object=npc['id'], move=self.move)
        memory.save()
        return True

    def step(self, state, overworld):
        if self.phase is None:
            return None
        if state.in_battle:
            self.finish('Field experiment interrupted by battle')
            return None
        self.ticks += 1
        frame = (tuple(getattr(state, 'screen_lines', ())), getattr(state, 'screen_cursor', None))
        self.repeats = self.repeats + 1 if frame == self.last else 0
        self.last = frame
        if self.ticks > 100 or self.repeats > 12:
            self.error = 'Field action did not produce a verified result'
            self.phase = 'close'
        if self.phase == 'close':
            if overworld:
                self.finish(self.error or 'Field action attempted; inspect obstacle response')
                return None
            if self.ticks > 120:
                self.finish('Field menu could not be closed')
                return None
            return 'b'
        if self.phase == 'start':
            if overworld:
                return 'start'
            button = (select_label(state, 'POK MON') or select_label(state, 'POKEMON')
                      or select_label(state, 'POKÉMON'))
            if button == 'a':
                self.phase = 'party'
            return button
        if self.phase == 'party':
            cursor = getattr(state, 'party_cursor', None)
            if cursor is None:
                return None
            button = party_step((1, cursor), self.slot)
            if button == 'a':
                self.phase = 'move'
            return button
        if self.phase == 'move':
            button = select_label(state, self.move)
            if button == 'a':
                self.phase = 'result'
            elif button is None and self.repeats >= 3:
                self.error = f'{self.move} is not offered in the observed menu'
                self.phase = 'close'
            return button
        if self.phase == 'result':
            if overworld:
                self.phase = 'close'
                if self.move == 'STRENGTH' and getattr(state, 'strength_active', None) is not True:
                    self.error = 'Strength activation was not verified; inspect the field response'
                    return None
                self.error = ''
                return self.direction
            if self.repeats >= 2:
                lines = ' '.join(line.strip() for line in state.screen_lines[12:] if line.strip())
                if lines and lines not in self.npc['pages']:
                    self.npc['pages'].append(lines)
                    classify(self.npc)
                    self.memory.save()
                # Only accept a visible Yes/No confirmation; other menus close.
                if getattr(state, 'screen_cursor', None) is not None:
                    return select_label(state, 'YES') or 'b'
                return 'a'
        return None

    def finish(self, result):
        self.npc['last_result'] = result
        self.memory.experience.record('field_result', object=self.npc['id'], result=result)
        self.memory.save()
        self.phase = None
