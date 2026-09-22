"""Durable experience and current-world facts have different rewind semantics."""

import json
from concurrent.futures import Future
from types import SimpleNamespace as NS

from jpp.agent.gold97_memory import Gold97Memory
from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.journey_knowledge import knowledge
from jpp.agent.journey_guidance import rank_candidates
from jpp.agent.notebook import notebook, export_notebook, text_lines
from jpp.gold97_collision import Gold97CollisionMap


def test_failure_survives_restore_and_reopen_but_new_evidence_allows_retry(tmp_path):
    path = tmp_path / 'memory.sqlite'
    memory = Gold97Memory('run', path)
    knowledge(memory)
    memory.checkpoint('before')
    target = {'id': 'exit:1', 'map': '09:02', 'kind': 'exit', 'cell': [1, 2]}
    memory.experience.fail(6, target, 'No transition')
    memory.restore('before')
    assert memory.experience.failures(6)[0]['target'] == 'exit:1'
    memory.close()
    memory = Gold97Memory('run', path)
    assert memory.experience.failures(6)
    assert not memory.experience.failures(7)
    knowledge(memory)['clues'].append({'map': '09:02', 'text': 'The door is unlocked'})
    assert not memory.experience.failures(6)
    assert memory.experience.recent()[-1]['kind'] == 'attempt_failed'
    memory.close()


def test_generic_word_overlap_cannot_claim_destination_priority():
    candidate = {'id': 'exit', 'kind': 'exit', 'destination': 'Route 101',
                 'destination_key': '14:0A', 'label': 'Continue to Route 101'}
    wrong = rank_candidates([candidate], 'Cut the tree on Route 102')[0]
    assert wrong['journey_reward'] == 25 and not wrong['goal_destination']
    right = rank_candidates([candidate], 'Explore Route 101')[0]
    assert right['goal_destination'] and right['journey_reward'] >= 100


def test_planner_can_finish_after_five_seconds_within_its_deadline(tmp_path, monkeypatch):
    controller = Gold97Controller('run', database=tmp_path / 'memory.sqlite', vision_enabled=False)
    try:
        strategy = controller.strategy
        strategy.data['enabled'] = True
        pending = Future()
        pending.set_running_or_notify_cancel()
        strategy.future = pending
        strategy.plan_started_at = 10
        monkeypatch.setattr('jpp.agent.journey_async.monotonic', lambda: 16)
        state = NS(map_group=9, map_number=2, x=1, y=1, map_width=6, map_height=6)
        terrain = Gold97CollisionMap((9, 2), 6, 6, bytes(36))
        assert strategy.options(state, terrain) == {}
        assert strategy.future is pending and not strategy.retired
        target = {'id': 'explore:1', 'kind': 'explore', 'cell': [3, 1],
                  'label': 'Explore', 'completion': 'Reach tile', 'map': '09:02'}
        monkeypatch.setattr('jpp.agent.journey_async.candidates', lambda *a, **k: [target])
        strategy.payload = {'candidates': [target], 'clues': []}
        pending.set_result(({'target': 'explore:1', 'explanation': 'Explore',
                             'completion': 'Reach tile', 'evidence': ['explore:1']}, {}))
        assert strategy.options(state, terrain) == {'right': 'Explore'}
        assert strategy.target == target
    finally:
        controller.close()


def test_action_outcome_and_export_are_evidence_based(tmp_path):
    controller = Gold97Controller('run', database=tmp_path / 'memory.sqlite', vision_enabled=False)
    try:
        memory = controller.memory
        state = NS(map_group=9, map_number=2, x=1, y=1, party=(), screen_lines=())
        memory.experience.action(state, 'right', 'executor', 1)
        memory.experience.observe(state)
        assert len(memory.experience.recent()) == 1
        state.x = 2
        memory.experience.observe(state)
        rows = memory.experience.recent()
        assert rows[0]['decision_id'] == rows[1]['id']
        assert not controller.route.completed
        memory.remember('clue', 'Door is locked', '09:02')
        output = export_notebook(controller, directory=tmp_path / 'notes')
        assert 'Door is locked' in output.read_text()
        data = json.loads(output.with_suffix('.json').read_text())
        assert any(event['kind'] == 'outcome' for event in data['events'])
        assert text_lines(notebook(controller), 'Learned', 'locked')
        assert text_lines(notebook(controller), 'Learned', 'absent') == ['No matching records']
    finally:
        controller.close()


def test_restore_interrupts_pending_action_without_inventing_result(tmp_path):
    memory = Gold97Memory('run', tmp_path / 'memory.sqlite')
    memory.checkpoint('before')
    state = NS(map_group=9, map_number=2, x=1, y=1, party=(), screen_lines=())
    memory.experience.action(state, 'a', 'executor', 1)
    memory.restore('before')
    assert memory.experience.pending is None
    outcome = memory.experience.recent()[1]
    assert 'unknown' in outcome['outcome'] and 'after' not in outcome
    memory.close()
