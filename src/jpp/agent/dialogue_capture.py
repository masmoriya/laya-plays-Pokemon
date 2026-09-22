"""Capture evidence before advancing dialogue, regardless of emulation speed."""


def before_advance(owner, state, frame):
    observation = owner.strategy.observations
    lines = getattr(state, 'screen_lines', ())
    text = ' '.join(line.strip() for line in (lines[12:] if len(lines) >= 18 else lines)
                    if line.strip())[:1500]
    readable = observation.readable(text)
    if not readable and frame is None:
        return
    key = f'{state.map_group:02X}:{state.map_number:02X}'
    if readable and observation.capture(text, key):
        observation.revision += 1
        owner.memory.save()
    # Keep a bounded page album, not a model request for every emulator frame.
    pages = getattr(owner, 'dialogue_captures', [])
    from zlib import crc32
    signature = text if readable else crc32(frame[-64:, :, :3].tobytes())
    if pages and pages[-1]['map'] == key and pages[-1]['signature'] == signature:
        return
    page = {'map': key, 'text': text if readable else '', 'signature': signature, 'frame': frame.copy() if frame is not None else None}
    if pages and pages[-1]['map'] == key and pages[-1]['text'] and text.startswith(pages[-1]['text']):
        pages[-1] = page
    else:
        pages.append(page)
    owner.dialogue_captures = pages[-3:]
