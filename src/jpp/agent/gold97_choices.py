"""Commit a dialogue answer once, then execute its visible menu position."""


def conversation_context(owner):
    observation = owner.strategy.observations
    pending = observation.pending or {}
    npc = observation.data['npcs'].get(pending.get('id'), {})
    return {'pages': npc.get('pages', [])[-6:],
            'rule': 'Decline optional purchases. Do not repeat a completed conversation without new objective evidence.'}


def yes_no_rows(lines, cursor=None):
    labels = [line.strip().upper() for line in lines]
    if cursor is not None:
        # Pop-up menus cover only the right side of a battle screen. HP and
        # names remain on the left of the same tilemap rows.
        labels = [line[cursor[0] + 1:].strip().upper()
                  if len(line) >= 20 else line.strip().upper() for line in lines]
    if 'YES' not in labels or 'NO' not in labels:
        return None
    return {'yes': labels.index('YES'), 'no': labels.index('NO')}


def choice_rows(state):
    return yes_no_rows(getattr(state, 'screen_lines', ()),
                       getattr(state, 'screen_cursor', None))


def choice_key(state):
    return (state.map_group, state.map_number,
            tuple(getattr(state, 'screen_lines', ())))


def answer_button(state, answer):
    rows = choice_rows(state)
    cursor = getattr(state, 'screen_cursor', None)
    if rows is None or cursor is None or answer not in rows:
        return None
    target = rows[answer]
    return 'a' if cursor[1] == target else 'up' if cursor[1] > target else 'down'


def dialogue_options(owner, state):
    """Offer meanings, not cursor movement; retain the choice until it closes."""
    rows = choice_rows(state)
    if rows is None:
        owner.dialogue_choice = None
        return None
    # An offer's identity is often on an earlier page, not the Yes/No page.
    import re
    text = ' '.join(conversation_context(owner)['pages'] + list(state.screen_lines)).upper()
    if re.search(r'\b(?:BUY|SELL|PRICE|COSTS?|SLOWPOKETAIL)\b', text):
        owner.dialogue_choice = (choice_key(state), 'no')
        button = answer_button(state, 'no')
        return {button: 'Decline the optional purchase'} if button else {}
    selected = getattr(owner, 'dialogue_choice', None)
    if selected and selected[0] == choice_key(state):
        button = answer_button(state, selected[1])
        return {button: f'Confirm {selected[1]}'} if button else {}
    owner.dialogue_choice = None
    return {'yes': 'Accept the offer or proceed with the action described in the dialogue',
            'no': 'Decline the offer or cancel the action described in the dialogue'}
