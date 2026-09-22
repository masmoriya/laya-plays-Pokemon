"""Visible conversations and pickups must not be starved by cart experiments."""
from types import SimpleNamespace as NS

from test_journey_strategy import controller, state
from jpp.agent.journey_targets import candidates
from jpp.agent.gold97_screen import TILEMAP, visible_rows
from jpp.gold97_collision import Gold97CollisionMap
from jpp.route_progress import RouteProgress


def scene(controller, girl_id='object:7'):
    s = state()
    s.map_group, s.map_number = 3, 13
    s.map_width, s.map_height = 30, 24
    s.x, s.y = 19, 15
    s.area_name, s.mechanics_verified = 'Boulder Mines 1F', True
    controller.route = RouteProgress(set(range(1, 12)))
    controller.memory.world['route'] = controller.route.to_dict()
    entities = [NS(key=identifier, kind=kind, pixel_x=x*16, pixel_y=y*16)
                for identifier, kind, x, y in ((girl_id, 'unknown', 22, 16),
                    ('object:3', 'item', 15, 18), ('object:6', 'obstacle', 19, 16))]
    controller.strategy.observe(s, entities, True)
    terrain = Gold97CollisionMap((3, 13), 30, 24, bytes(30*24))
    return s, terrain


def test_visible_rescue_then_item_outrank_cart(controller):
    s, terrain = scene(controller)
    tasks = candidates(s, controller.memory, terrain)
    assert [task['id'] for task in tasks[:2]] == ['03:0D/object:7', '03:0D/object:3']
    assert tasks[0]['rescue_interaction']
    assert tasks[0]['kind'] == 'talk'
    # Standing beside an object is not the completion criterion.
    assert tasks[0]['completion'] == 'Dialogue observed and closed'
    assert controller.route.now == 12


def test_generic_unvisited_person_beats_cart_without_known_identity(controller):
    s, terrain = scene(controller, 'person')
    tasks = candidates(s, controller.memory, terrain)
    person = next(t for t in tasks if t['id'].endswith('/person'))
    cart = next(t for t in tasks if t['id'].endswith('/object:6'))
    assert person['journey_reward'] > cart['journey_reward']
    assert not person['rescue_interaction']


def test_stale_cart_plan_yields_to_visible_girl(controller):
    s, terrain = scene(controller)
    cart = next(t for t in candidates(s, controller.memory, terrain) if t.get('category') == 'obstacle')
    cart['journey_reward'] = 300  # A plan retained from the old ranking.
    controller.strategy.target = cart
    controller.strategy.options(s, terrain)
    assert controller.strategy.target['id'] == '03:0D/object:7'


def test_no_hidden_or_unreachable_rescue_target_is_invented(controller):
    s, terrain = scene(controller)
    girl = controller.strategy.data['npcs']['03:0D/object:7']
    girl['visible'] = False
    assert not any(t.get('rescue_interaction') for t in candidates(s, controller.memory, terrain))
    girl['visible'] = True
    walls = Gold97CollisionMap((3, 13), 30, 24, bytes([7]) * (30*24))
    assert not any(t.get('rescue_interaction') for t in candidates(s, controller.memory, walls))


def test_punctuation_only_dialogue_is_readable():
    memory = bytearray([0x7F]) * 0x10000
    memory[TILEMAP + 14 * 20 + 1] = 0xF2  # Actual rescue page: charmap ellipsis.
    lines, _ = visible_rows(memory)
    assert lines[14].strip() == '…'


def test_last_seen_unfinished_person_stays_ahead_of_cart(controller):
    s, terrain = scene(controller)
    data = controller.strategy.data['npcs']
    data['03:0D/object:7']['visible'] = False
    data['03:0D/object:3'].update(outcome='collected', status='resolved')
    tasks = candidates(s, controller.memory, terrain)
    assert tasks[0]['id'] == '03:0D/object:7'
    assert tasks[0]['reobserve_interaction'] and tasks[0]['kind'] == 'explore'
    assert not tasks[0]['rescue_interaction']  # Re-observe before claiming she is there.


def test_pickup_requires_face_and_a_instead_of_just_arrival(controller):
    s, terrain = scene(controller)
    s.x, s.y, s.player_facing = 15, 17, 'down'
    controller.strategy.observations.state = s
    item = next(t for t in candidates(s, controller.memory, terrain) if t.get('category') == 'item')
    controller.strategy.target = item
    for _ in range(25):
        options = controller.strategy.options(s, terrain)
    assert options == {'a': 'Collect the observed item'}
    controller.strategy.chosen('a')
    assert controller.strategy.observations.pending['id'] == item['id']
    assert controller.strategy.data['npcs'][item['id']]['outcome'] != 'collected'
