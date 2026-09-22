"""HM execution must follow verified capabilities instead of stale search plans."""
from types import SimpleNamespace as NS

from test_journey_strategy import controller, state
from jpp.agent.field_actions import field_confirmation, strength_push
from jpp.agent.hm_teaching import HMTeaching
from jpp.agent.object_memory import attempt, evidence_key


def hm_state():
    s = state()
    s.mechanics_verified = True
    s.owned_hms = ('Cut', 'Strength')
    s.badge_ids = ('johto_1', 'johto_2')
    s.party = (NS(identity='cut', species='TANGELA', moves=('Cut',), species_data=None),
               NS(identity='strength', species='VOLBEAR', moves=('Scratch', 'Leer'),
                  species_data=NS(field_moves=('Strength',))))
    s.screen_cursor, s.party_cursor = None, None
    return s


def test_ownership_and_manual_teaching_cancel_stale_acquisition_plan(controller):
    s = hm_state()
    s.owned_hms = ('Cut',)
    controller.strategy.observe(s, (), True)
    for change in ('acquire', 'teach'):
        controller.strategy.target = {'id': 'search', 'kind': 'explore', 'cell': [3, 3]}
        controller.strategy.data['plan'] = {'explanation': 'Look for Strength'}
        controller.strategy.excluded.add('old-attempt')
        if change == 'acquire':
            s.owned_hms = ('Cut', 'Strength')
        else:
            s.party[1].moves += ('Strength',)
        controller.strategy.observe(s, (), True)
        assert controller.strategy.target is None
        assert controller.strategy.data['plan'] is None
        assert not controller.strategy.excluded


def test_explicit_strength_offer_accepts_only_a_learned_unlocked_move():
    s = hm_state()
    s.screen_lines = ('YES', 'NO', 'Want to use STRENGTH?')
    s.screen_cursor = (0, 1)
    assert field_confirmation(s) is None  # Ownership is insufficient.
    s.party[1].moves += ('Strength',)
    assert field_confirmation(s) == 'up'  # Move off a previously selected No.
    s.screen_cursor = (0, 0)
    assert field_confirmation(s) == 'a'
    s.badge_ids = ('johto_1',)
    assert field_confirmation(s) is None
    s.badge_ids = ('johto_1', 'johto_2')
    s.screen_lines = ('YES', 'NO', 'Want to buy this item?')
    assert field_confirmation(s) is None


def test_active_strength_enables_only_bounded_push_attempts(controller):
    s = hm_state()
    npc = {'id': 'cart', 'cell': [2, 1], 'pages': ['A Pokemon may be able to move this.']}
    assert not strength_push(s, npc, controller.memory)
    s.strength_active = True
    assert strength_push(s, npc, controller.memory)
    for _ in range(2):
        attempt(npc, evidence_key(s, npc, controller.memory), 'push')
    assert not strength_push(s, npc, controller.memory)
    npc['outcome'] = 'moved'
    assert not strength_push(s, npc, controller.memory)


def test_teaching_checks_actual_offer_and_party_result():
    s = hm_state()
    teaching = HMTeaching()
    assert teaching.start(s, 12)
    assert teaching.plan['slot'] == 1
    teaching.phase = 'offer'
    s.screen_lines = ('H4 STRENGTH', 'YES', 'NO') + ('',) * 9 + ('Teach CUT to a POKEMON?',)
    s.screen_cursor = (0, 1)
    assert teaching.step(s, False) == 'b'
    assert teaching.error and teaching.phase == 'close'
    teaching = HMTeaching()
    assert teaching.start(s, 12)
    s.party[1].moves += ('Strength',)
    assert teaching.step(s, True) is None
    assert teaching.phase is None and not teaching.error
    assert not teaching.start(s, 12)


def test_teaching_will_not_replace_a_different_party_member():
    s = hm_state()
    teaching = HMTeaching()
    assert teaching.start(s, 12)
    s.party = s.party[:1]
    teaching.step(s, False)
    assert teaching.error == 'Party changed during HM teaching'
