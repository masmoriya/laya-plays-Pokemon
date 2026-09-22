"""Pack decision essentials against the loaded model's actual tokenizer budget."""

def pack_context(state, questions, agent):
    from laya.common import build_sequence, serialize_state

    question = agent._to_internal(questions['next_action'])
    maximum = int(agent.cfg.get('max_len', 512))
    head = int(agent.cfg.get('head_max_len', 192))
    empty, _ = build_sequence(agent.tok, '', question, maximum, head)
    budget = maximum - len(empty)
    if budget <= 0:
        raise ValueError('Laya question leaves no context budget')

    def size(value):
        text = serialize_state(value).replace(agent.tok.mask_token, ' ')
        return len(agent.tok(text, add_special_tokens=False)['input_ids'])

    journey = state.get('journey') or {}
    ordered = {
        'goal': state.get('goal'),
        'decision_kind': state.get('decision_kind'),
        'conversation': state.get('conversation'),
        'progress': journey.get('progress'),
        'strategy': state.get('strategy'),
        'navigation_memory': journey.get('navigation_memory'),
        'hm_next': (journey.get('hm_journey') or {}).get('instruction'),
        'map': state.get('map'), 'position': state.get('position'),
        'screen_text': state.get('screen_text'), 'battle': state.get('battle'),
        'travel': {key: (journey.get('travel') or {}).get(key)
                   for key in ('destination', 'next_map', 'next_stop') if key in journey['travel']} if journey.get('travel') else None,
        'hm_pending': (journey.get('hm_journey') or {}).get('pending'),
        'next_tasks': [{'task': item.get('label'), 'journey_reward': item.get('journey_reward', 0)}
                       for item in journey.get('candidates', [])[:4]],
        'operator_guidance': journey.get('operator_guidance'),
        'operator_notes': journey.get('operator_notes'),
        'context_mode': journey.get('context_mode'),
        'route_progress': journey.get('route_progress'),
        'prerequisites': (journey.get('prerequisites') or {}).get('instruction'),
        'failed_attempts': [{'target': item['target'], 'reason': item['reason'][:120]}
                            for item in journey.get('failed_attempts', [])[-3:]],
        'recent': journey.get('recent', [])[-4:],
        'party': state.get('party'), 'memory': state.get('memory'),
        'clues': journey.get('clues', [])[-4:],
        'navigation': journey.get('navigation'),
    }
    ordered.update({k: v for k, v in state.items() if k not in ordered and k != 'journey'})
    packed, omitted = {}, []
    for key, value in ordered.items():
        if value is None or value == []:
            continue
        candidate = {**packed, key: value}
        if size(candidate) <= budget:
            packed[key] = value
            continue
        if isinstance(value, list):
            kept = []
            for item in value:
                if size({**packed, key: kept + [item]}) > budget:
                    break
                kept.append(item)
            if kept:
                packed[key] = kept
        omitted.append(key)
    # Never quietly decide without the objective or current interaction screen.
    for key in ('goal', 'decision_kind', 'conversation', 'map', 'position', 'battle', 'screen_text'):
        if state.get(key) and packed.get(key) != state[key]:
            raise ValueError(f'Laya context budget cannot retain essential {key}')
    if journey.get('navigation_memory') and packed.get('navigation_memory') != journey['navigation_memory']:
        raise ValueError('Laya context budget cannot retain essential navigation_memory')
    if journey.get('progress') and packed.get('progress') != journey['progress']:
        raise ValueError('Laya context budget cannot retain essential progress')
    if state.get('strategy') and packed.get('strategy') != state['strategy']:
        raise ValueError('Laya context budget cannot retain essential strategy')
    return packed, {'budget': budget, 'retained_tokens': size(packed),
                    'submitted_tokens': size(state), 'omitted_fields': omitted,
                    'retained_fields': list(packed)}
