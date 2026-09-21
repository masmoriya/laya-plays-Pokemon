"""Eggs must not keep Pokémon Center recovery running."""

from types import SimpleNamespace

import pytest

from jpp.decode import Mon
from jpp.agent.gold97_controller import Gold97Controller
from jpp.agent.gold97_services import fully_recovered, needs_healing


def party_state(hp=30, status='none', pp=(20,)):
    return SimpleNamespace(
        in_battle=False, map_group=10, map_number=14,
        area_name='Westport Pokémon Center 1F', x=5, y=3,
        map_width=16, map_height=8, last_spawn_map=(10, 1),
        party=(
            Mon(slot=1, species='TANGTRIP', level=10, hp=hp, max_hp=30,
                status=status, types=('GRASS',), moves=('VINE WHIP',), pp=pp, max_pp=(20,)),
            Mon(slot=2, species='EGG', level=5, hp=0, max_hp=19,
                status='none', types=(), moves=(), pp=()),
        ),
    )


def test_healthy_party_with_egg_does_not_need_another_heal():
    state = party_state()
    assert not needs_healing(state)
    assert fully_recovered(state)


@pytest.mark.parametrize('kwargs', [{'hp': 0}, {'status': 'poison'}, {'pp': (0,)}])
def test_egg_does_not_hide_a_party_member_needing_healing(kwargs):
    state = party_state(**kwargs)
    assert needs_healing(state)
    assert not fully_recovered(state)


def test_healing_completes_and_does_not_restart_with_egg(tmp_path):
    controller = Gold97Controller('egg-heal', database=tmp_path / 'proof.sqlite',
                                  vision_enabled=False)
    try:
        state = party_state(hp=0)
        assert controller._recovery_action(state, overworld=True) == 'up'
        assert controller._recovery_action(state, overworld=True) == 'a'
        state.party = party_state().party
        assert controller._recovery_action(
            state, overworld=False, prompt_visible=True) == 'a'
        assert controller.recovery['exit']
        state.y = 7
        assert controller._recovery_action(state, overworld=True) == 'down'
        state.map_number, state.area_name = 1, 'Westport'
        for _ in range(3):
            assert controller._recovery_action(state, overworld=True) is None
            assert controller.recovery is None
    finally:
        controller.close()
