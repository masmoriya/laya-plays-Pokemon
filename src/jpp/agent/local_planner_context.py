"""Bound local planning input while retaining actionable evidence and target IDs."""
import json


def select(value, fields):
    return {key: value[key] for key in fields if key in value}


def compact(value):
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, list):
        return [compact(item) for item in value[:6]]
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items()}
    return value


def planner_context(payload):
    result = compact(select(payload, ('goal', 'map', 'directive', 'operator_guidance',
        'operator_notes', 'route_progress', 'failed_attempts', 'recent')))
    result['candidates'] = [select(item, ('id', 'kind', 'cell', 'label', 'completion',
        'journey_reward', 'reward_reason', 'destination_key', 'prerequisite',
        'goal_route', 'goal_interaction')) for item in payload['candidates'][:8]]
    result['clues'] = [select(item, ('id', 'text', 'map')) for item in payload.get('clues', [])[-4:]]
    navigation = payload.get('navigation') or {}
    result['navigation'] = compact(select(navigation, ('position', 'exits', 'fresh',
        'destination', 'entities', 'nearby_terrain')))
    result['dialogue'] = [select(item, ('id', 'pages', 'status'))
                          for item in payload.get('interactions', []) if item.get('pages')][-3:]
    result['dialogue'] = [{**item, 'pages': [p[:300] for p in item['pages'][-2:]]}
                          for item in result['dialogue']]
    result['connections'] = compact(payload.get('connections', [])[-4:])
    world = payload.get('world') or {}
    result['world'] = select(world, ('source', 'location', 'badges', 'owned_hms', 'trail'))
    journey = world.get('journey') or {}
    result['world']['journey'] = select(journey, ('current', 'goal', 'next', 'completed'))
    guidance = journey.get('guidance') or {}
    result['world']['journey']['guidance'] = select(guidance, ('known', 'next', 'instruction', 'completion'))
    dex = world.get('pokedex') or {}
    result['world']['pokedex'] = select(dex, ('caught_count', 'seen_count', 'ownership_note'))
    result['world']['pokedex']['caught_species'] = dex.get('caught_species', [])[:20]
    result['world']['pokedex']['listed_count'] = len(dex.get('caught_species', [])[:20])
    hm = payload.get('hm_journey') or {}
    result['hm_journey'] = compact(select(hm, ('instruction', 'active', 'pending')))
    result['prerequisites'] = compact(payload.get('prerequisites'))
    result['party'] = compact((payload.get('team') or {}).get('party', []))
    # Candidate IDs are never shortened: the executor validates them verbatim.
    # Reserve space for the prompt, schema, image tokens and response in 8K KV.
    while len(json.dumps(result, ensure_ascii=False)) > 6500:
        for key in ('recent', 'operator_notes', 'connections'):
            if key in result:
                del result[key]
                break
        else:
            if len(result['candidates']) > 1:
                result['candidates'].pop()
            elif len(result['clues']) > 1:
                result['clues'].pop(0)
            elif result.get('dialogue'):
                result['dialogue'].pop(0)
            elif result.get('failed_attempts'):
                result['failed_attempts'].pop(0)
            elif 'nearby_terrain' in result['navigation']:
                del result['navigation']['nearby_terrain']
            elif 'entities' in result['navigation']:
                del result['navigation']['entities']
            elif result.get('prerequisites'):
                result['prerequisites'] = None
            elif result.get('clues'):
                result['clues'].pop(0)
            else:
                raise ValueError('Planner context exceeds the local input budget')
    return result
