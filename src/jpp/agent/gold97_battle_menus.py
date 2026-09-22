"""Verified battle menu controls, separate from turn lifecycle."""

def party_step(cursor, target):
    if cursor is None:
        return None
    current = cursor[1]
    target += 1
    if current == 0:
        return 'up'
    if current != target:
        return 'down' if current < target else 'up'
    return 'a'


def root_step(cursor, target):
    if cursor is None:
        return None
    if cursor[0] != target[0]:
        return 'right' if cursor[0] < target[0] else 'left'
    if cursor[1] != target[1]:
        return 'down' if cursor[1] < target[1] else 'up'
    return 'a'


def heal_step(executor, state, lines, frame, signature):
    """Only confirm a visibly selected Potion and its USE command."""
    cursor = getattr(state, 'screen_cursor', None)
    if frame == executor.confirmed:
        return None
    if executor.phase == 'heal_result':
        executor.confirmed = frame
        return 'a'
    if cursor is None:
        return None
    row = next((i for i, line in enumerate(lines)
                if line.strip().upper().split()[0:1] == ['POTION']), None)
    if executor.phase == 'use_potion':
        use = next((i for i, line in enumerate(lines) if line[cursor[0] + 1:].strip().upper() == 'USE'
                    or line.strip().upper() == 'USE'), None)
        if use is None:
            return None
        if cursor[1] != use:
            return 'down' if cursor[1] < use else 'up'
        executor.confirmed = frame
        return 'a'
    if row is None:
        return 'b'  # unidentified pocket: cancel without spending an item
    if cursor[1] != row:
        return 'down' if cursor[1] < row else 'up'
    executor.phase = 'use_potion'
    executor.confirmed = frame
    return 'a'
