"""Cartridge-backed rescue guidance; no invented objects or completed actions.

Pinned source: 976507f9e6e605050384e9ec12e9651988ae7c46.
Mine block and collision tables were matched byte-for-byte to v6.1c.
"""

from .gold97_mechanics import REFERENCE


MINE_MAPS = {(3, 13), (3, 14), (3, 15), (3, 44), (3, 45), (3, 46)}


def rescue_speaker(state, milestone, npc):
    """Object 7 is the girl in the verified 1F script, even when she turns/walks."""
    return (milestone == 12 and getattr(state, 'mechanics_verified', False)
            and (state.map_group, state.map_number) == (3, 13)
            and npc.get('id') == '03:0D/object:7' and npc.get('visible', False)
            and 'observed_from' not in npc)


def rank_rescue(targets, reward):
    for target in targets:
        if target.get('rescue_interaction'):
            target.update(prerequisite=True, investigation_priority=True,
                          journey_reward=reward * 6, label='Talk to the missing girl',
                          source=REFERENCE['source'] + 'maps/BoulderMines1F.asm',
                          reward_reason='Visible reachable NPC for the current rescue objective')
    return sorted(targets, key=lambda t: -t.get('journey_reward', 0))


def mine_context(state, milestone):
    key = (getattr(state, 'map_group', None), getattr(state, 'map_number', None))
    if (milestone != 12 or not getattr(state, 'mechanics_verified', False)
            or key not in MINE_MAPS | {(4, 5), (4, 7)}):
        return None
    owned = 'Strength' in getattr(state, 'owned_hms', ())
    learned = any(move.upper() == 'STRENGTH' for mon in getattr(state, 'party', ())
                  for move in mon.moves)
    strength = ('Strength learned' if learned else 'Strength owned, not taught' if owned
                else 'Strength is on B4F at (24, 9)')
    return {
        'source': REFERENCE['source'] + 'maps/BoulderMines1F.asm',
        'known': strength + '; the girl is on 1F.',
        'next': ('Find the girl near (22, 16) on 1F. No Surf needed.' if key == (3, 13)
                 else 'Return to 1F and find the girl near (22, 16). No Surf needed.'),
        'instruction': (
            'Rescue the girl on Boulder Mines 1F near (22, 16). A dry route from '
            'the entrance avoids every Strength cart. Do not search deep floors '
            'for the girl, Surf, or an alternate outside entrance. Follow only '
            'reachable observed candidates; source coordinates do not reveal terrain.'),
        'steps': [
            'From 1F entrance (2, 14), use stairs (3, 11) to emerge at (17, 3) on 1F.',
            'Follow the dry corridor south to (17, 10), east to (23, 10), '
            'south to (23, 13), west to (19, 13), then south to the girl near (22, 16).',
            'Talk to the girl; her script returns you to the mine entrance.',
        ],
        'field_moves': {
            'strength_owned': owned, 'strength_learned': learned,
            'strength': 'HM04 on B4F (24, 9); teach a compatible Pokemon; Hive Badge required.',
            'surf': 'Elder rewards HM03 after the Slowpoke Well B2F Rocket event; Fog Badge required.',
        },
        'completion': 'Observe the rescue event flag; reaching the girl is not completion.',
    }
