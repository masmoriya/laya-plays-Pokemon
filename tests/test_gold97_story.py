"""Story flags advance only the corresponding observed milestone."""
from types import SimpleNamespace as NS

from jpp.gold97_story import story_milestones
from jpp.route_progress import RouteProgress


def test_story_events_are_exact_build_and_bit_scoped():
    memory = bytearray(0x10000)
    memory[0xDA94] = 0x10
    memory[0xDB69] = 0x01
    assert story_milestones(memory, True, (4,5)) == ()
    memory[0xDB69] |= 0x02
    assert story_milestones(memory, True, (4,5)) == (12,)
    memory[0xDA94] |= 0x20
    assert story_milestones(memory, True, (4,5)) == (12,13)
    memory[0xDA94] |= 0x40
    assert story_milestones(memory, True, (4,5)) == (12,13,14)
    assert story_milestones(memory, False) == ()


def test_route_does_not_treat_planning_or_arrival_as_rescuing_the_child():
    route = RouteProgress(set(range(1,12)))
    state = NS(area_name='Boulder Mines 1F',party=(),badge_ids=(),
               mechanics_verified=True,story_milestones=())
    route.observe(state)
    assert route.now == 12
    state.story_milestones = (12,)
    route.observe(state)
    assert route.now == 13
    state.story_milestones = (12,13,14)
    state.mechanics_verified = False
    route.observe(state)
    assert route.now == 13


def test_initial_warning_flag_is_not_story_completion():
    memory = bytearray(0x10000)
    memory[0xDA94] = 0x20
    assert story_milestones(memory, True, (4,5)) == ()
    memory[0xDB69] = 0x02
    assert story_milestones(memory, True, (3,13)) == (11,12)


def test_legacy_initial_warning_is_not_saved_as_story_progress():
    assert 13 not in RouteProgress.from_dict({'completed': [1, 13]}).completed
    assert 13 in RouteProgress.from_dict({'completed': [12, 13]}).completed
    assert 13 in RouteProgress.from_dict({'completed': [13], 'manual_history': [13]}).completed
