"""Dialogue offers and missing-person detours retain their actual evidence."""
from test_journey_strategy import controller, state, sprite
from jpp.agent.gold97_choices import dialogue_options, conversation_context
from jpp.agent.journey_guidance import rank_candidates
from jpp.agent.navigation_memory import allowed_targets


def test_route_mention_does_not_make_seller_a_goal():
    seller = {'id': 'seller', 'kind': 'talk', 'label': 'Talk to an unvisited sprite'}
    result = rank_candidates([seller],
        'After Whitney clears the Route 103 Slowpoke, travel to Birdon Town',
        current_area='Route 103')[0]
    assert not result['goal_interaction']
    assert result['journey_reward'] < 100
    gym = rank_candidates([seller], 'Defeat Whitney in Teknos Gym', current_area='Teknos Gym')[0]
    assert gym['goal_interaction']


def test_offer_on_previous_page_is_declined_and_answer_stays_committed(controller):
    s = state()
    obs = controller.strategy.observations
    obs.observe(s, (sprite(),), overworld=True, milestone=6)
    identifier = next(iter(obs.data['npcs']))
    obs.interacted(identifier)
    obs.capture('tasty, nutritious SLOWPOKETAIL?', '09:02')
    s.screen_lines = ('YES', 'NO', 'You will want this!')
    s.screen_cursor = (0, 0)
    assert list(dialogue_options(controller, s)) == ['down']
    s.screen_cursor = (0, 1)
    assert list(dialogue_options(controller, s)) == ['a']
    assert 'SLOWPOKETAIL' in conversation_context(controller)['pages'][0]
    obs.pending = None
    controller.dialogue_choice = None
    assert set(dialogue_options(controller, s)) == {'yes', 'no'}


def test_missing_person_detour_survives_replanning_and_changed_approach(controller):
    s = state()
    strategy = controller.strategy
    strategy.observe(s, (sprite(),), True)
    identifier = next(iter(strategy.data['npcs']))
    target = dict(id=identifier, kind='explore', map='09:02', cell=[1, 1],
                  direction='right', reobserve_interaction=True, label='Recheck person')
    strategy.target = target
    for _ in range(24):
        strategy.observe(s, (), True)
    assert strategy.target is None
    assert not allowed_targets(controller.memory, controller.route.now, [target])
    alternate = {**target, 'cell': [2, 1], 'direction': 'left'}
    controller.memory.world['discovery_revision'] = 123
    strategy.invalidate()
    assert not allowed_targets(controller.memory, controller.route.now, [alternate])
    # Re-observing the person is real new evidence, unlike another camera tile.
    strategy.observe(s, (sprite(),), True)
    assert allowed_targets(controller.memory, controller.route.now, [alternate])
