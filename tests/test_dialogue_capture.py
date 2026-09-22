"""Fast playback must retain a page before pressing the advance button."""
import numpy as np
from test_journey_strategy import controller, state, sprite
from jpp.agent.dialogue_capture import before_advance
from jpp.agent.local_vision import LocalJourneyProvider


def test_page_is_saved_without_waiting_for_repeated_observations(controller):
    s = state()
    observation = controller.strategy.observations
    observation.observe(s, (sprite(),), overworld=True, milestone=6)
    identifier = next(iter(observation.data['npcs']))
    observation.interacted(identifier)
    s.screen_lines = ('The missing girl is in the mines.',)
    frame = np.zeros((144, 160, 4), dtype=np.uint8)
    assert observation.stable == 0
    before_advance(controller, s, frame)
    assert observation.data['npcs'][identifier]['pages'] == [s.screen_lines[0]]
    assert observation.pending['saw_text']
    assert controller.dialogue_captures[0]['frame'] is not frame
    before_advance(controller, s, frame)
    assert len(controller.dialogue_captures) == 1
    payload = controller.strategy.context(s)
    payload['candidates'] = [{'id': 'mine', 'completion': 'Arrive', 'label': 'Investigate'}]
    context = LocalJourneyProvider().model_input(payload)['state']
    assert context['dialogue'][0]['pages'] == [s.screen_lines[0]]


def test_dialogue_album_is_bounded(controller):
    s = state()
    for index in range(6):
        s.screen_lines = (f'This is dialogue page number {index}.',)
        before_advance(controller, s, np.zeros((144, 160, 4), dtype=np.uint8))
    assert len(controller.dialogue_captures) == 3
