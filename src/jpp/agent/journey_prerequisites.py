"""Exact-build story prerequisites, separate from movement and completion.

Source revision 976507f9e6e605050384e9ec12e9651988ae7c46:
Route103.asm, Route103WestportGate.asm, WestportCity.asm,
WestportPortPassage.asm, WestportPort.asm and TeknosPort.asm.
Only rank candidates already proven reachable by the navigation layer.
"""

from .gold97_mechanics import REFERENCE


SOURCE = REFERENCE['source'] + 'maps/WestportPort.asm'
FERRY_STEPS = {11, 12, 13, 14, 15}
WESTPORT_PORT = (14, 1)


def ferry_goal(state, milestone):
    return bool(getattr(state, 'mechanics_verified', False)
                and milestone in FERRY_STEPS)


def ferry_speaker(state, milestone, npc):
    return (ferry_goal(state, milestone)
            and (state.map_group, state.map_number) == WESTPORT_PORT
            and npc.get('map') == '0E:01'
            and npc.get('cell') == [7, 16]
            and npc.get('visible', False)
            and 'observed_from' not in npc)


def ferry_menu_options(state, milestone):
    """Select only the visible, objective-matching dock destination."""
    if not ferry_goal(state, milestone) or (state.map_group, state.map_number) != WESTPORT_PORT:
        return None
    lines = tuple(line.strip().upper() for line in getattr(state, 'screen_lines', ()))
    cursor = getattr(state, 'screen_cursor', None)
    if cursor is None or 'TEKNOS CITY' not in lines or 'CANCEL' not in lines:
        return None
    row = lines.index('TEKNOS CITY')
    action = 'a' if cursor[1] == row else 'up' if cursor[1] > row else 'down'
    return {action: 'Take the ferry to Teknos City'}


def prerequisite_context(state, milestone):
    from .mine_guidance import mine_context
    mine = mine_context(state, milestone)
    if mine:
        return mine
    if not ferry_goal(state, milestone):
        return None
    return {
        'source': SOURCE,
        'instruction': ('Reach Teknos via Westport Port Passage and the dock sailor; '
                        'select Teknos City. Route 103 goes to Birdon and its '
                        'Slowpoke need Whitney defeated first. Backtrack to the ferry.'),
        'steps': [
            'Defeat Bugsy to open Westport Docks (Hive Badge).',
            'Return to Westport City and enter Westport Port Passage.',
            'Use the passage stairs to reach Westport Port.',
            'Talk to the sailor at (7, 16) and select Teknos City.',
            'Leave Teknos Port through its passage into Teknos City.',
        ],
        'blocker': ('Route 103 leads to Birdon, not Teknos. Its Slowpoke leave '
                    'after EVENT_BEAT_WHITNEY; the Westport Rocket takeover '
                    'is not a prerequisite for the Teknos ferry.'),
        'slowpoke_cleared': getattr(state, 'route_103_slowpoke_cleared', None),
        'completion': 'Observe arrival in Teknos City; planning or talking is not arrival.',
    }


def rank_prerequisites(targets, state, milestone, reward):
    if not ferry_goal(state, milestone):
        return targets
    key = (state.map_group, state.map_number)
    next_map = {
        (8, 4): '09:08',  # Route 103 -> gate -> Westport, even on a return visit.
        (9, 8): '0A:01',
        (10, 1): '0A:19',
        (10, 25): '0E:01',
        (14, 2): '04:08',
        (4, 8): '04:05',
    }.get(key)
    # These passages have disconnected rooms linked by same-map stairs.
    # Choose forward stairs only when the final exit is not reachable.
    has_exit = any(t.get('destination_key') == next_map for t in targets)
    stairs = {(10, 25): [15, 4], (4, 8): [3, 2]}.get(key)
    for target in targets:
        forward = (target['kind'] == 'exit' and next_map is not None
                   and target.get('destination_key') == next_map)
        forward |= (target['kind'] == 'exit' and not has_exit and stairs is not None
                    and target.get('destination_key') == f'{key[0]:02X}:{key[1]:02X}'
                    and target['cell'] == stairs)
        forward |= bool(target.get('ferry_interaction'))
        if forward:
            target.update(prerequisite=True, source=SOURCE,
                          journey_reward=reward * 3,
                          reward_reason='Verified prerequisite route: Westport ferry to Teknos')
        # Do not offer the Birdon detour as a competing route to Teknos.
        if key == (9, 8) and target.get('destination_key') == '08:04':
            target.update(journey_reward=0, route_frontier=False)
        if key == (8, 4) and target.get('destination_key') == '08:05':
            target.update(journey_reward=0, route_frontier=False)
    return sorted(targets, key=lambda t: -t.get('journey_reward', 0))
