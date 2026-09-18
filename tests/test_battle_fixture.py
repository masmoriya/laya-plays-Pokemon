import pytest

from jpp import options, policy
from jpp.decode import decode
from jpp.goals import GOALS

import fake_jev
import make_ram

GOAL = next(g for g in GOALS if g.name == "win_lab_rival")


@pytest.fixture
def fake():
    def start(answers=None):
        url, shutdown = fake_jev.serve(answers)
        started.append(shutdown)
        return policy.Policy(policy.JevClient(base_url=url, api_key="test"))

    started = []
    yield start
    for shutdown in started:
        shutdown()


@pytest.fixture
def branch():
    ram = make_ram.battle()
    return options.battle_branch(decode(bytes(ram)), GOAL, turn=3)


def test_a_legal_choice_becomes_the_button_sequence(fake, branch):
    decision = fake().decide(branch)
    assert decision.option == "use_move_ember" and not decision.fell_back
    assert decision.probabilities["use_move_ember"] == 0.71
    assert decision.nouls == {"faints_this_turn": 0.23, "should_flee": 0.08}
    assert decision.latency_ms > 0
    state = decode(bytes(make_ram.battle()))
    assert options.buttons_for(state, branch, decision.option) == ["a", "down", "down", "a"]


def test_an_illegal_option_id_takes_the_code_default(fake, branch):
    answers = {"next_action": {"type": "choice", "choice": "use_move_hyper_beam",
                               "confidence": 0.99, "probabilities": {"use_move_hyper_beam": 0.99}}}
    decision = fake(answers).decide(branch)
    assert decision.fell_back and "unusable option" in decision.reason
    assert decision.option == "use_move_scratch"  # the only neutral move against WATER


def test_other_is_not_a_pressable_option(fake, branch):
    answers = {"next_action": {"type": "choice", "choice": "other", "confidence": 0.4,
                               "probabilities": {"other": 0.4}}}
    decision = fake(answers).decide(branch)
    assert decision.fell_back and decision.option == "use_move_scratch"


def test_an_unreachable_endpoint_fails_open_to_the_code_default(branch):
    dead = policy.Policy(policy.JevClient(base_url="http://127.0.0.1:1", api_key="x"))
    decision = dead.decide(branch)
    assert decision.fell_back and decision.option == "use_move_scratch"
    assert "Error" in decision.reason or "error" in decision.reason


def test_the_no_progress_cap_forces_the_default_without_a_call(fake, branch):
    decision = fake().decide(branch, forced=True)
    assert decision.fell_back and decision.reason == "no progress cap reached"
    assert decision.latency_ms == 0.0


def test_one_request_carries_the_choice_and_both_nouls(branch):
    questions = policy.questions_for(branch)
    assert list(questions) == ["next_action", "faints_this_turn", "should_flee"]
    assert questions["next_action"]["type"] == "choice"


def test_the_code_default_prefers_effectiveness_over_order():
    ram = make_ram.battle()
    branch = options.battle_branch(decode(bytes(ram)), GOAL)
    option, why = policy.default_option(branch)
    assert (option, why) == ("use_move_scratch", "highest-effectiveness move")
