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


def test_ferry_prerequisite_reaches_actual_tokenizer(agent):
    from jpp.agent.journey_prerequisites import prerequisite_context
    from jpp.route_progress import MAIN

    prerequisite = prerequisite_context(SimpleNamespace(mechanics_verified=True), 11)
    state = {'goal': MAIN[11], 'decision_kind': 'dialogue', 'map': 'Westport Port',
             'position': [7, 15], 'screen_text': ['TEKNOS CITY', 'CANCEL'],
             'journey': {'prerequisites': prerequisite},
             'memory': ['Old observations'] * 500}
    packed, meta = pack_context(state, _questions({'a': 'Confirm', 'b': 'Cancel'}), agent)
    assert packed['prerequisites'] == prerequisite['instruction']
    assert packed['screen_text'] == state['screen_text']
    assert meta['retained_tokens'] <= meta['budget']


def test_travel_next_hop_reaches_laya_tokenizer(agent):
    state = {'goal': 'Reach Birdon Town', 'decision_kind': 'explore',
             'map': 'Teknos City', 'position': [23, 13],
             'journey': {'travel': {'destination': 'Birdon Town', 'next_map': '04:08'}},
             'memory': ['Old observations'] * 500}
    packed, meta = pack_context(state, _questions({'down': 'Travel to Teknos Port Passage'}), agent)
    assert packed['travel'] == state['journey']['travel']
    assert meta['retained_tokens'] <= meta['budget']


def test_navigation_memory_is_protected_under_pressure(agent):
    summary = {'objective': 17, 'arrived_from': '09:08',
               'failed': ['geometry:0A:01:22:5: Repeated map cycle'],
               'recent': ['up: Moved [22, 6] to [22, 5]'],
               'unresolved': ['unknown:1 at [12, 4]']}
    state = {'goal': 'Reach Birdon Town after Whitney clears Route 103',
             'decision_kind': 'explore', 'map': 'Westport City', 'position': [22, 6],
             'journey': {'navigation_memory': summary}, 'memory': ['Old history'] * 500}
    packed, meta = pack_context(state, _questions({'left': 'Investigate exit', 'up': 'Gate'}), agent)
    assert packed['navigation_memory'] == summary
    assert meta['retained_tokens'] <= meta['budget']
    assert 'memory' in meta['omitted_fields']


def test_active_offer_survives_context_pressure(agent):
    conversation = {'pages': ['How would you like this SLOWPOKETAIL?', 'It costs 1000000.'],
                    'rule': 'Decline optional purchases.'}
    state = {'goal': 'Travel to Birdon Town', 'decision_kind': 'dialogue',
             'map': 'Route 103', 'position': [9, 13],
             'screen_text': ['YES', 'NO', 'You will want this!'],
             'conversation': conversation, 'memory': ['Old observation'] * 500}
    packed, _ = pack_context(state, _questions({'yes': 'Accept', 'no': 'Decline'}), agent)
    assert packed['conversation'] == conversation


def test_progress_and_qwen_handoff_are_protected(agent):
    progress = {'task':'Defeat Morty', 'success':'Fog Badge observed',
                'hm': {'move':'Surf', 'action':'badge', 'party_compatible':[],
                       'boxed':[], 'badge_ready':False,
                       'next':'Defeat Morty; catch a compatible Pokemon when encountered'},
                'avoid':['03:11:(9, 11)'], 'rule':'No repeated exits without new prerequisites'}
    strategy = {'target':'gym', 'explanation':'Earn the badge needed for Surf',
                'completion':'Fog Badge observed', 'evidence':['gym']}
    state = {'goal':'Defeat Morty', 'decision_kind':'explore', 'map':'Birdon Town',
             'position':[15,10], 'screen_text':[], 'strategy':strategy,
             'journey':{'progress':progress}, 'memory':['Old observation']*500}
    packed, _ = pack_context(state, _questions({'up':'Gym','down':'Explore'}), agent)
    assert packed['progress'] == progress
    assert packed['strategy'] == strategy
