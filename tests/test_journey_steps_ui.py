"""The expanded HM checklist is reachable and all steps can be paged through."""
import os
from types import SimpleNamespace

import pygame

from jpp.agent.journey_hms import hm_journey
from jpp.field_moves import HMS
from jpp.journey_checklist import journey_steps
from jpp.live_notebook import NotebookPanel
from jpp.live_ui import LiveUI, SIZE
from jpp.route_progress import RouteProgress


def test_steps_button_opens_paged_checklist_for_every_hm():
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    try:
        ui = LiveUI(pygame.display.set_mode(SIZE))
        ui.panels.stages(SimpleNamespace(route=RouteProgress()))
        assert 'agent_open:Steps' in ui.actions
        panel = NotebookPanel()
        panel.action('agent_open:Steps', None)
        steps = journey_steps(hm_journey(SimpleNamespace(mechanics_verified=True), 70))
        panel.update({'strategy': {'journey_steps': steps}})
        rendered = []
        original = ui.text

        def record(value, *args, **kwargs):
            rendered.append(str(value))
            return original(value, *args, **kwargs)

        ui.text = record
        for _ in range(10):
            panel.draw(ui)
            assert not ui.actions['agent_view:Steps'].colliderect(ui.actions['notebook'])
            if 'notes_next' not in ui.actions:
                break
            panel.action('notes_next', None)
        else:
            raise AssertionError('Checklist pagination never reached its end')
        for move in HMS:
            assert f'Pending · Obtain HM{move.number:02d} {move.name}' in rendered
            assert f'Pending · Teach {move.name}' in rendered
        assert panel.page > 0
    finally:
        pygame.quit()
