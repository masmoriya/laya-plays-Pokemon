"""Westport ferry prerequisites must beat the Route 103/Birdon detour."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from test_journey_strategy import controller, state, sprite
from test_route103_recovery import route103
from jpp.agent.journey_prerequisites import prerequisite_context, rank_prerequisites
from jpp.agent.journey_targets import candidates
from jpp.gold97_adapter import Gold97Adapter
from jpp.gold97_catalog import map_details
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import MAIN, RouteProgress


def test_verified_route103_returns_to_gate_even_when_just_entered(controller):
    s, terrain = route103(controller)
    s.mechanics_verified = True
    controller.strategy.arrived_from = '09:08'
    controller.strategy.options(s, terrain)
    assert controller.strategy.target['destination_key'] == '09:08'
    assert controller.strategy.target['prerequisite']
    assert controller.strategy.future is None
    assert controller.route.now == 11


@pytest.mark.parametrize('group,number,exits,expected', [
    (9, 8, ((4, 0, '', 8, 4), (4, 7, '', 10, 1)), '0A:01'),
    (10, 1, ((22, 5, '', 9, 8), (4, 8, '', 10, 25)), '0A:19'),
    (10, 25, ((19, 4, '', 10, 1), (15, 4, '', 10, 25)), '0A:19'),
    (10, 25, ((3, 2, '', 10, 25), (3, 14, '', 14, 1)), '0E:01'),
    (14, 2, ((7, 5, '', 4, 8),), '04:08'),
    (4, 8, ((3, 14, '', 14, 2), (3, 2, '', 4, 8)), '04:08'),
    (4, 8, ((14, 16, '', 4, 8), (13, 14, '', 4, 5)), '04:05'),
])
def test_ferry_legs_use_reachable_exits(controller, group, number, exits, expected):
    s = state()
    s.map_group, s.map_number = group, number
    s.area_name, _, s.map_width, s.map_height = map_details(group, number)
    s.mechanics_verified, s.map_exits = True, exits
    controller.route = RouteProgress(set(range(1, 11)))
    controller.memory.world['route'] = controller.route.to_dict()
    controller.strategy.observe(s, (), True)
    terrain = Gold97CollisionMap((group, number), s.map_width, s.map_height,
                                bytes(s.map_width * s.map_height))
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]['destination_key'] == expected
    assert tasks[0]['prerequisite']


def test_sailor_can_be_revisited_until_arrival_without_inventing_npcs(controller):
    s = state()
    s.map_group, s.map_number, s.x, s.y = 14, 1, 7, 15
    s.area_name, _, s.map_width, s.map_height = map_details(14, 1)
    s.mechanics_verified = True
    controller.route = RouteProgress(set(range(1, 11)))
    controller.memory.world['route'] = controller.route.to_dict()
    controller.strategy.observe(s, (sprite(7, 16),), True)
    terrain = Gold97CollisionMap((14, 1), 20, 36, bytes(720))
    npc = next(iter(controller.strategy.data['npcs'].values()))
    npc['status'] = 'talked'  # Earlier visit, cancellation, or pre-Bugsy maintenance.
    task = candidates(s, controller.memory, terrain)[0]
    assert task['ferry_interaction'] and task['prerequisite']
    assert task['cell'] == [7, 15]
    assert task['direction'] == 'down'
    npc['visible'] = False
    assert not any(t.get('ferry_interaction') for t in candidates(s, controller.memory, terrain))


def test_prerequisites_are_version_and_objective_scoped():
    s = state()
    assert prerequisite_context(s, 11) is None
    s.mechanics_verified = True
    assert prerequisite_context(s, 17) is None
    assert prerequisite_context(s, 12) is not None
    context = prerequisite_context(s, 11)
    assert 'EVENT_BEAT_WHITNEY' in context['blocker']
    assert 'select Teknos City' in ' '.join(context['steps'])
    # A guide cannot fabricate an unreachable exit.
    assert rank_prerequisites([], s, 11, 100) == []


def test_ferry_progress_requires_arrival_and_keeps_saved_ids():
    route = RouteProgress.from_dict({'completed': list(range(1, 11))})
    s = state()
    s.area_name = 'Westport Port'
    route.observe(s)
    assert route.now == 11
    s.area_name = 'Teknos Port'
    route.observe(s)
    assert route.now == 11
    s.area_name = 'Teknos City'
    route.observe(s)
    assert route.now == 12  # Missing-child investigation still needs evidence.
    assert len(MAIN) == 127
    assert RouteProgress.from_dict(route.to_dict()).now == 12


def test_cartridge_whitney_flag_and_passage_geometry():
    rom = Path('Gold 97 Reforged v6.1c.gbc')
    if not rom.exists():
        pytest.skip('requires the user-owned v6.1c cartridge')
    adapter = Gold97Adapter(rom)
    assert adapter.mechanics_verified
    # Exact cartridge event header: forward stairs and the dock exit.
    assert bytes([0, 0, 5, 4, 19, 14, 10, 1, 5, 19, 15, 10, 1,
                  4, 15, 4, 10, 25, 2, 3, 3, 10, 25, 14, 3, 1, 14, 1]) in adapter.data.rom
    # Read both real Slowpoke object records, not just a source-derived address.
    header = bytes([0, 0, 2, 49, 12, 1, 9, 8, 49, 13, 2, 9, 8])
    offset = adapter.data.rom.index(header) + len(header)
    offset += 1 + adapter.data.rom[offset] * 8  # coordinate events
    offset += 1 + adapter.data.rom[offset] * 5  # background events
    assert adapter.data.rom[offset] == 11
    for index, x in ((7, 10), (8, 11)):
        start = offset + 1 + index * 13
        record = adapter.data.rom[start:start + 13]
        assert (record[2] - 4, record[1] - 4) == (x, 28)
        assert int.from_bytes(record[-2:], 'little') == 1221
    memory = bytearray(0x10000)
    emulator = SimpleNamespace(memory=memory)
    assert adapter.snapshot(emulator).state.route_103_slowpoke_cleared is False
    memory[0xDB0A] = 0x10  # Adjacent event is not Whitney.
    assert adapter.snapshot(emulator).state.route_103_slowpoke_cleared is False
    memory[0xDB0A] = 0x20
    assert adapter.snapshot(emulator).state.route_103_slowpoke_cleared is True
    adapter.mechanics_verified = False
    assert adapter.snapshot(emulator).state.route_103_slowpoke_cleared is None


def test_planner_context_exposes_missing_steps(controller):
    s, _ = route103(controller)
    s.mechanics_verified = True
    context = controller.strategy.context(s)
    assert context['prerequisites']['steps'][0].startswith('Defeat Bugsy')
    assert 'Westport Docks ferry' in context['goal']
