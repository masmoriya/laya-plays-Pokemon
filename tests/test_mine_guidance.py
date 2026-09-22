"""Missing journey history and HM ownership are distinct from learned moves."""
from types import SimpleNamespace as NS

from jpp.gold97_story import story_milestones
from jpp.route_progress import RouteProgress
from jpp.agent.journey_prerequisites import prerequisite_context
from jpp.agent.mine_guidance import mine_context


def set_event(memory, flag):
    memory[0xDA72 + flag // 8] |= 1 << (flag % 8)


def test_advanced_save_recovers_early_history_without_completing_rescue():
    memory = bytearray(0x10000)
    for flag in (32, 31, 1220):
        set_event(memory, flag)
    memory[0xD987] = 2
    state = NS(mechanics_verified=True, area_name='Boulder Mines B3F',
               map_group=3, map_number=46, badge_ids=('johto_1', 'johto_2'),
               received_cut_from_bill=True, route_102_tree_chopped=True,
               route_102_rival_complete=True,
               story_milestones=story_milestones(memory, True, (3, 46)))
    route = RouteProgress()
    route.observe(state)
    assert route.now == 12
    assert route.completed == set(range(1, 12))
    assert RouteProgress.from_dict(route.to_dict()).now == 12
    assert not route.manual_history


def test_prebattle_scene_does_not_complete_rival_and_wrong_rom_is_ignored():
    memory = bytearray(0x10000)
    set_event(memory, 32)
    memory[0xD987] = 3
    assert story_milestones(memory, True) == (1,)
    memory[0xD987] = 4
    assert story_milestones(memory, True) == (1, 2)
    assert story_milestones(memory, False, (3, 46)) == ()
    assert story_milestones(bytearray(0x10000), True, (3, 46)) == (11,)


def test_owned_strength_does_not_claim_a_party_member_can_use_it():
    state = NS(mechanics_verified=True, map_group=3, map_number=46,
               owned_hms=('Cut', 'Strength'), party=(NS(moves=('Cut',)),))
    context = prerequisite_context(state, 12)
    assert context['field_moves']['strength_owned']
    assert not context['field_moves']['strength_learned']
    assert 'not taught' in context['known']
    assert '1F' in context['next'] and 'No Surf' in context['next']
    assert 'dry route' in context['instruction']
    state.party = (NS(moves=('Strength',)),)
    assert mine_context(state, 12)['field_moves']['strength_learned']
    assert mine_context(state, 13) is None
    state.mechanics_verified = False
    assert mine_context(state, 12) is None
