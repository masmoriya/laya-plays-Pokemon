"""Unfinished leader objectives survive previously recorded conversations."""
from types import SimpleNamespace as NS

import pytest

from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.journey_knowledge import knowledge
from jpp.agent.journey_objective import objective_speaker
from jpp.agent.journey_targets import candidates
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


@pytest.mark.parametrize('page, expected', [
    ('I  BUGSY.', 'Bugsy'), ('I am BUGSY.', 'Bugsy'), ("I'm BUGSY.", 'Bugsy'),
    ('BUGSY  young, but his knowledge of', None),
    ('I think BUGSY is strong.', None),
])
def test_identity_requires_observed_introduction(page, expected):
    npc = {'map': '0A:18', 'pages': [page]}
    assert objective_speaker(npc, 'Defeat Bugsy in Westport Gym') == expected
    assert objective_speaker(npc, 'Continue toward Teknos City') is None
    npc['map'] = '0A:01'
    assert objective_speaker(npc, 'Defeat Bugsy in Westport Gym') is None


@pytest.mark.parametrize('enabled', [False, True])
def test_recorded_bugsy_is_approached_faced_and_challenged(tmp_path, enabled):
    owner = Gold97Controller('bugsy', database=tmp_path / 'agent.sqlite', vision_enabled=False)
    try:
        owner.route = RouteProgress(set(range(1, 10)))
        owner.memory.world['route'] = owner.route.to_dict()
        data = knowledge(owner.memory)
        data['enabled'] = enabled
        identifier = '0A:18/object:1'
        # Actual saved evidence: introduction recorded as talked, no badge,
        # and the leader may be outside the current viewport.
        data['npcs'][identifier] = {
            'id': identifier, 'map': '0A:18', 'cell': [5, 7],
            'status': 'talked', 'attempts': 1, 'milestone': 10,
            'completed_milestone': 10, 'pages': ['I  BUGSY.'], 'visible': False,
        }
        state = NS(map_group=10, map_number=24, x=5, y=9, map_width=10,
                   map_height=18, area_name='Westport Gym', in_battle=False,
                   badge_ids=(1,), party=(), screen_lines=(),
                   battle=NS(kind='none', opponent=None),
                   map_exits=((5, 17, 'down', 10, 1),))
        terrain = Gold97CollisionMap((10, 24), 10, 18, bytes(180))
        targets = candidates(state, owner.memory, terrain)
        assert targets[0]['id'] == identifier
        assert targets[0]['label'] == 'Challenge Bugsy'
        assert not any(t['kind'] == 'explore' for t in targets)
        strategy = owner.strategy
        assert strategy.options(state, terrain) == {'up': 'Challenge Bugsy'}
        assert strategy.future is None
        state.y = 8
        for _ in range(24):
            assert strategy.options(state, terrain) == {}
        assert strategy.options(state, terrain) == {'up': 'Face the sprite before speaking'}
        strategy.chosen('up')
        assert strategy.options(state, terrain) == {'a': 'Talk to the sprite'}
        strategy.chosen('a')
        assert strategy.observations.pending['id'] == identifier
        owner.memory.world['route']['completed'].append(10)
        assert not any(t['id'] == identifier for t in candidates(state, owner.memory, terrain))
    finally:
        owner.close()
