"""Missing HM prerequisites remain explicit beyond the main story milestone."""
from types import SimpleNamespace

import pytest

from jpp.agent.journey_hms import hm_journey, rank_hm_targets
from jpp.field_moves import HMS, capabilities
from jpp.journey_checklist import checklist_lines, journey_steps
from jpp.route_progress import RouteProgress


def observed(missing=None):
    names = [move.name for move in HMS if move.name != missing]
    return SimpleNamespace(
        mechanics_verified=True, owned_hms=names,
        badge_ids=[f'johto_{number}' for number in range(1, 9)],
        map_group=10, map_number=1,
        party=[SimpleNamespace(moves=list(names), species_data=None)])


@pytest.mark.parametrize('move', HMS, ids=lambda move: move.name)
def test_every_missed_hm_remains_actionable_after_its_stage(move):
    result = hm_journey(observed(move.name), move.stage + 1)
    assert result['active']['name'] == move.name
    assert result['active']['action'] == 'obtain'
    assert result['pending'][0]['next'] == f'Obtain HM{move.number:02d} {move.name}'
    steps = journey_steps(result)
    assert len(steps) == 35
    assert len({step['id'] for step in steps}) == 35
    assert any(move.acquisition in line for line in checklist_lines({'journey_steps': steps}))


def test_future_hm_does_not_displace_current_story():
    assert hm_journey(observed('Surf'), 19)['active'] is None
    surf = next(row for row in capabilities(observed('Surf'), 19) if row['name'] == 'Surf')
    assert surf['steps'][0]['status'] == 'later'


def test_owned_learned_badge_and_ready_are_distinct():
    state = observed('Surf')
    state.owned_hms.append('Surf')
    surf = next(row for row in capabilities(state, 22) if row['name'] == 'Surf')
    assert surf['owned'] and not surf['ready']
    assert surf['next'] == 'Bring a Pokemon that can learn Surf'
    state.party[0].moves.append('SURF')
    state.badge_ids.remove('johto_4')
    result = hm_journey(state, 22)
    assert result['active'] is None
    assert 'Morty' in result['instruction']
    state.badge_ids.append('johto_4')
    surf = next(row for row in capabilities(state, 22) if row['name'] == 'Surf')
    assert surf['ready'] and surf['steps'][-1]['status'] == 'ready'
    assert 'ready for field use' in surf['steps'][-1]['label']


def test_boxed_quagsire_surf_capability_becomes_an_explicit_teaching_task():
    from jpp.agent.hm_preparation import preparation
    state = observed('Surf')
    state.owned_hms = ('Surf',)
    state.party = [SimpleNamespace(identity='quagsire-1', species='QUAGSIRE',
                                   moves=['Mud Slap', 'Mist', 'Slam'],
                                   species_data=SimpleNamespace(field_moves=('Surf',)))]
    result = preparation(state, 20)
    assert result['action'] == 'teach'
    assert result['move'] == 'Surf'
    assert result['next'] == 'Teach Surf to QUAGSIRE'
    assert not next(row for row in capabilities(state, 20)
                    if row['name'] == 'Surf')['ready']
    state.party[0].moves.append('Surf')
    assert next(row for row in capabilities(state, 20)
                if row['name'] == 'Surf')['ready']


def test_unknown_cartridge_never_claims_completion_or_selects_acquisition():
    state = observed()
    state.mechanics_verified = False
    result = hm_journey(state, 60)
    assert result['active'] is None
    assert all(step['status'] == 'unknown' for step in journey_steps(result))


def test_missing_hms_remain_visible_after_story_completion():
    assert hm_journey(observed('Strength'), None)['active']['name'] == 'Strength'


def test_acquisition_uses_multiple_observed_exits_and_only_reachable_candidates():
    state = observed('Strength')
    memory = SimpleNamespace(world={'journey_strategy': {'connections': [
        {'from': '0A:01', 'to': '04:05'},
        {'from': '04:05', 'to': '03:2C'},
    ]}})
    targets = [{'id': 'forward', 'kind': 'exit', 'destination_key': '04:05'},
               {'id': 'other', 'kind': 'exit', 'destination_key': '09:08'}]
    ranked = rank_hm_targets(targets, state, 22, 100, memory)
    assert ranked[0]['id'] == 'forward'
    assert ranked[0]['prerequisite'] and ranked[0]['investigation_priority']
    assert 'Strength' in ranked[0]['label']
    assert rank_hm_targets([], state, 22, 100, memory) == []


def test_substeps_do_not_renumber_or_complete_story_steps():
    route = RouteProgress(set(range(1, 22)))
    before = route.to_dict()
    state = observed('Surf')
    state.badge_ids = state.badge_ids[:4]
    route.observe(state)
    assert route.to_dict() == before
    assert route.now == 22
    assert len(route.field_moves) == 7
