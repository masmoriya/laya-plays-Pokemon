"""Check token retention with the installed checkpoint tokenizer, without inference."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jpp.laya_config import setting
from jpp.laya_sidecar import _questions
from jpp.agent.tactical_context import pack_context


@pytest.fixture
def agent():
    pytest.importorskip('laya')
    from laya.agent import Agent
    from transformers import AutoTokenizer
    path = setting('model_path')
    if not path or not Path(path).exists():
        pytest.skip('Provide local LAYA_MODEL_PATH for exact tokenizer proof')
    return SimpleNamespace(cfg=json.loads((Path(path) / 'rl_agent_config.json').read_text()),
                           tok=AutoTokenizer.from_pretrained(str(Path(path) / 'tokenizer'), local_files_only=True),
                           _to_internal=Agent._to_internal)


def test_journey_survives_oversized_input_and_actual_sdk_does_not_truncate(agent):
    from laya.common import build_sequence
    state = {'goal': 'Reach Route 102', 'decision_kind': 'explore', 'map': 'Pagota City',
             'position': [1, 1], 'party': [{'species': 'VOLBEAR', 'hp': 20}] * 200,
             'strategy': {'target': 'exit:1', 'explanation': 'Take the west exit'},
             'journey': {'failed_attempts': [{'target': 'door:1', 'reason': 'Locked'}]},
             'memory': ['Old observations'] * 500}
    questions = _questions({'left': 'West exit', 'right': 'Explore east'})
    packed, meta = pack_context(state, questions, agent)
    assert packed['strategy'] == state['strategy']
    assert packed['failed_attempts'] == state['journey']['failed_attempts']
    assert meta['submitted_tokens'] > meta['budget']
    assert meta['retained_tokens'] <= meta['budget'] and 'party' in meta['omitted_fields']
    q = agent._to_internal(questions['next_action'])
    normal, _ = build_sequence(agent.tok, packed, q, agent.cfg['max_len'], agent.cfg['head_max_len'])
    unlimited, _ = build_sequence(agent.tok, packed, q, 10000, agent.cfg['head_max_len'])
    assert normal == unlimited


def test_essential_screen_cannot_be_silently_dropped(agent):
    with pytest.raises(ValueError, match='essential screen_text'):
        pack_context({'goal': 'Read menu', 'screen_text': ['Very long menu ' * 2000]},
                     _questions({'a': 'Confirm', 'b': 'Cancel'}), agent)
