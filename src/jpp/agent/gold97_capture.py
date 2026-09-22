"""Ball-pocket execution: identify the item and wait through the animation."""

_POCKET_SCAN_LIMIT = 4


def ball_step(executor, state, lines, frame, signature):
    cursor = getattr(state, 'screen_cursor', None)
    text = ' '.join(' '.join(lines).upper().split())
    # Once thrown, input cannot improve the result. Only advance the result page.
    if executor.phase == 'throw':
        if frame == executor.confirmed:
            return None
        if any(word in text for word in ('BROKE FREE', 'APPEARED TO BE CAUGHT',
                                         'ALMOST HAD', 'GOTCHA', 'CAUGHT!', 'MISSED', 'SO CLOSE', 'IT WAS SO', 'OH, NO', 'OH NO')):
            executor.confirmed, executor.phase = frame, 'ball_result'
            return 'a'
        return None
    if executor.phase == 'ball_result':
        if frame == executor.confirmed:
            return None
        executor.confirmed = frame
        return 'a'  # Result observed; advance retaliation/dialogue, not the animation.
    if executor.phase == 'use_ball':
        row = next((i for i, line in enumerate(lines)
                    if 'USE' in line.upper().split()), None)
        if row is not None and cursor is None:
            # The item context menu opens on USE. Some frames expose its text
            # before the blinking cursor tile, so confirming the default is
            # safer than leaving a selected ball pending forever.
            executor.confirmed, executor.before, executor.phase = frame, signature, 'throw'
            return 'a'
        if row is None:
            # The item confirmation tap can be ignored while the submenu is
            # drawing. The controller spaces calls with its menu cooldown, so
            # retry the visibly selected ball instead of waiting indefinitely.
            ball_row = next((i for i, line in enumerate(lines)
                             if 'POK' in line.upper() and 'BALL' in line.upper()), None)
            if ball_row is not None and cursor is not None and cursor[1] == ball_row:
                executor.confirmed = frame
                return 'a'
            return None
        if cursor[1] != row:
            return 'down' if cursor[1] < row else 'up'
        executor.confirmed, executor.before, executor.phase = frame, signature, 'throw'
        return 'a'
    if cursor is None:
        return None
    row = next((i for i, line in enumerate(lines)
                if 'POK' in line.upper() and 'BALL' in line.upper()), None)
    if row is not None:
        executor.pocket_search_steps = 0
        if frame == executor.confirmed:
            return None
        if cursor[1] != row:
            return 'down' if cursor[1] < row else 'up'
        executor.confirmed, executor.phase = frame, 'use_ball'
        return 'a'
    if 'CANCEL' in text or any(item in text for item in ('POTION', 'ANTIDOTE', 'PARLYZ HEAL', 'ESCAPE ROPE')):
        # Search every reversible pocket rather than treating the first pocket
        # as evidence that the requested item is unavailable. Do not mark this
        # frame confirmed: a missed D-pad poll must be retried on the next
        # controller pass. After a full scan, back out and reopen the Pack.
        executor.pocket_search_steps = getattr(executor, 'pocket_search_steps', 0) + 1
        if executor.pocket_search_steps >= _POCKET_SCAN_LIMIT:
            executor.pocket_search_steps = 0
            executor.confirmed = None
            return 'b'
        return 'right'
    return None
