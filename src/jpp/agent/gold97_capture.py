"""Ball-pocket execution: identify the item and wait through the animation."""


def ball_step(executor, state, lines, frame, signature):
    cursor = getattr(state, 'screen_cursor', None)
    if frame == executor.confirmed:
        return None
    text = ' '.join(' '.join(lines).upper().split())
    # Once thrown, input cannot improve the result. Only advance the result page.
    if executor.phase == 'throw':
        if any(word in text for word in ('BROKE FREE', 'APPEARED TO BE CAUGHT',
                                         'ALMOST HAD', 'GOTCHA', 'CAUGHT!', 'MISSED', 'SO CLOSE', 'IT WAS SO', 'OH, NO', 'OH NO')):
            executor.confirmed, executor.phase = frame, 'ball_result'
            return 'a'
        return None
    if executor.phase == 'ball_result':
        executor.confirmed = frame
        return 'a'  # Result observed; advance retaliation/dialogue, not the animation.
    if cursor is None:
        return None
    if executor.phase == 'use_ball':
        row = next((i for i, line in enumerate(lines) if line.strip().upper() == 'USE'), None)
        if row is None:
            return None
        if cursor[1] != row:
            return 'down' if cursor[1] < row else 'up'
        executor.confirmed, executor.before, executor.phase = frame, signature, 'throw'
        return 'a'
    row = next((i for i, line in enumerate(lines)
                if 'POK' in line.upper() and 'BALL' in line.upper()), None)
    if row is not None:
        if cursor[1] != row:
            return 'down' if cursor[1] < row else 'up'
        executor.confirmed, executor.phase = frame, 'use_ball'
        return 'a'
    if 'CANCEL' in text or any(item in text for item in ('POTION', 'ANTIDOTE', 'PARLYZ HEAL', 'ESCAPE ROPE')):
        executor.confirmed = frame
        return 'right'  # ITEMS -> BALL pocket, no unidentified item confirmation.
    return None
