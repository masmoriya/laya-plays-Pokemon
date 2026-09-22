"""Generic navigation contracts, independent of model responses and story routes."""
from dataclasses import replace

from test_navigation_continuity import owner, state, terrain
from jpp.agent.journey_targets import candidates, target_options
from jpp.agent.navigation_policy import preferred_targets
from jpp.agent.object_memory import classify, close_interaction, eligible
from jpp.agent.local_vision import LocalJourneyProvider
from jpp.terrain_capture import OverworldSprite
from jpp.navigation_metrics import NavigationMetrics


def test_collectibles_survive_travel_filter_and_emergency_retreat_wins():
    route = {'id': 'route', 'travel_route': True, 'kind': 'exit'}
    item = {'id': 'item', 'category': 'item', 'kind': 'talk'}
    tree = {'id': 'tree', 'category': 'resource', 'kind': 'talk'}
    assert preferred_targets([route, item, tree]) == [item, tree]
    retreat = {'id': 'retreat', 'retreat_reason': 'Recover health'}
    assert preferred_targets([route, item, retreat]) == [retreat]


def test_resource_requires_result_and_remains_solid_after_harvest(owner):
    s = state()
    tree = OverworldSprite('tree', '03:0D', 3*16, 16, bytes(1024), kind='resource')
    owner.strategy.observe(s, (tree,), True)
    obj = owner.strategy.data['npcs']['03:0D/tree']
    obj['pages'] = ["It's a fruit-bearing tree."]
    close_interaction(obj)
    assert obj['outcome'] == 'unresolved'
    assert eligible(obj, 'evidence')
    obj['pages'].append('Obtained a BERRY!')
    classify(obj)
    assert obj['outcome'] == 'harvested'
    assert not eligible(obj, 'changed-evidence')
    from jpp.agent.navigation_paths import paths
    assert (3, 1) not in paths(s, owner.memory, terrain())


def test_resource_empty_and_full_bag_are_not_pickups():
    full = {'category': 'resource', 'pages': ["It's a BERRY! But the PACK is full."]}
    close_interaction(full)
    assert full['outcome'] == 'unresolved'
    empty = {'category': 'resource', 'pages': ["There's nothing here…"]}
    close_interaction(empty)
    assert empty['outcome'] == 'exhausted'
    assert not eligible(empty, 'evidence')


def test_resource_empty_evidence_is_captured_for_the_active_interaction(owner):
    s = state()
    tree = OverworldSprite('tree', '03:0D', 3*16, 16, bytes(1024), kind='resource')
    obs = owner.strategy.observations
    obs.observe(s, (tree,), overworld=True, milestone=12)
    obs.interacted('03:0D/tree')
    assert obs.capture("There's nothing here…", '03:0D')
    obs.observe(s, (tree,), overworld=True, milestone=12)
    assert obs.data['npcs']['03:0D/tree']['outcome'] == 'exhausted'


def test_new_reward_evidence_classifies_immediately_and_restore_rolls_it_back(owner):
    s = state()
    tree = OverworldSprite('tree', '03:0D', 3*16, 16, bytes(1024), kind='resource')
    obs = owner.strategy.observations
    obs.observe(s, (tree,), overworld=True, milestone=12)
    owner.memory.checkpoint('before-harvest')
    obs.interacted('03:0D/tree')
    assert obs.capture('Obtained a BERRY!', '03:0D')
    assert owner.memory.world['journey_strategy']['npcs']['03:0D/tree']['outcome'] == 'harvested'
    owner.memory.restore('before-harvest')
    from jpp.agent.journey_knowledge import knowledge
    assert knowledge(owner.memory)['npcs']['03:0D/tree']['outcome'] == 'seen'


def test_active_exit_detours_to_pickup_and_remembers_return(owner):
    s = state(map_exits=((7, 1, 'right', 3, 14),))
    item = OverworldSprite('pickup', '03:0D', 3*16, 16, bytes(1024), kind='item')
    owner.strategy.data['enabled'] = False
    owner.strategy.observe(s, (item,), True)
    tasks = candidates(s, owner.memory, terrain())
    route = next(t for t in tasks if t['kind'] == 'exit')
    owner.strategy.target = route
    owner.strategy.options(s, terrain())
    assert owner.strategy.target['id'] == '03:0D/pickup'
    assert owner.strategy.data['resume_target']['target']['id'] == route['id']
    owner.strategy.data['npcs']['03:0D/pickup'].update(outcome='collected', status='resolved')
    owner.strategy.invalidate()
    assert owner.strategy.options(s, terrain())
    assert owner.strategy.target['id'] == route['id']
    assert 'resume_target' not in owner.strategy.data


def test_one_target_needs_no_background_model(owner):
    s = state()
    item = OverworldSprite('pickup', '03:0D', 3*16, 16, bytes(1024), kind='item')
    owner.strategy.provider = LocalJourneyProvider()
    owner.strategy.data['enabled'] = True
    owner.strategy.observe(s, (item,), True)
    assert owner.strategy.options(s, terrain())
    assert owner.strategy.future is None
    assert set(t['id'] for t in owner.strategy.local_targets.values()) == {'03:0D/pickup'}


def test_route_cost_chooses_accessible_side_instead_of_near_side_behind_wall(owner):
    # The west face looks closest but requires walking around the whole wall.
    s = state(x=1, y=1, map_width=8, map_height=6)
    road = {(1,1),(1,2),(1,3),(2,3),(3,3),(4,3),(4,2),(5,2),
            (6,2),(6,1),(6,0),(5,0),(4,0),(3,0),(3,1)}
    ground = replace(terrain(), height=6, tiles=bytes(
        0 if (x, y) in road else 7 for y in range(6) for x in range(8)))
    item = OverworldSprite('pickup', '03:0D', 4*16, 16, bytes(1024), kind='item')
    owner.strategy.observe(s, (item,), True)
    task = next(t for t in candidates(s, owner.memory, ground) if t.get('category') == 'item')
    assert task['cell'] == [4, 2] and task['path_steps'] == 6
    assert target_options(task, s, owner.memory, ground) == {'down': task['label']}


def test_run_metrics_do_not_count_historical_pickups_as_new(owner):
    s = state()
    tree = OverworldSprite('tree', '03:0D', 3*16, 16, bytes(1024), kind='resource')
    owner.strategy.observe(s, (tree,), True)
    obj = owner.strategy.data['npcs']['03:0D/tree']
    obj.update(outcome='harvested', status='resolved')
    metrics = NavigationMetrics(owner.memory)
    for frame, x in enumerate([1, 2, 1, 2]):
        s.x = x
        metrics.observe(owner, s, True, frame)
    result = metrics.summary(owner)
    assert result['steps'] == 3 and result['repeated_steps'] == 1
    assert result['immediate_reversals'] == 2
    assert not result['new_pickups'] and not result['pending_collectibles']


def test_run_metrics_keep_a_rewound_discovery_unresolved(owner):
    s = state()
    owner.memory.checkpoint('before-discovery')
    tree = OverworldSprite('tree', '03:0D', 3*16, 16, bytes(1024), kind='resource')
    owner.strategy.observe(s, (tree,), True)
    metrics = NavigationMetrics(owner.memory)
    metrics.observe(owner, s, True, 0)
    owner.memory.restore('before-discovery')
    assert metrics.summary(owner)['pending_collectibles'] == ['03:0D/tree']


def test_held_travel_releases_for_a_reachable_pickup_off_the_path(owner):
    from jpp.agent.route_execution import committed_heading
    s = state(x=2)
    item = OverworldSprite('pickup', '03:0D', 5*16, 2*16, bytes(1024), kind='item')
    owner.strategy.observe(s, (item,), True)
    owner.terrain = terrain()
    owner.strategy.target = dict(id='exit', map='03:0D', kind='exit', cell=[7,1],
                                 direction='right', label='Continue')
    assert not committed_heading(owner, s, 'right')
    owner.strategy.data['npcs']['03:0D/pickup'].update(outcome='collected', status='resolved')
    assert committed_heading(owner, s, 'right')
