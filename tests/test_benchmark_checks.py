"""Coverage gates do not turn a timeout or old progress into success."""
from jpp.benchmark_checks import check_run


def result():
    return {'new_verified_milestones': [3], 'event_counts': {'loop_recovery': 1},
            'navigation': {'new_pickups': ['item', 'resource'], 'pending_collectibles': [],
                           'departures_with_pending_collectibles': []}}


def test_measurement_alone_has_no_pass_claim():
    assert check_run(result()) == []


def test_explicit_requirements_must_all_pass():
    checks = check_run(result(), milestones=[3], pickups=2, collect_observed=True, max_loops=1)
    assert len(checks) == 4 and all(c['passed'] for c in checks)
    assert not all(c['passed'] for c in check_run(result(), milestones=[2], pickups=3, max_loops=0))


def test_passing_a_missed_item_then_returning_is_reported():
    data = result()
    data['navigation']['departures_with_pending_collectibles'] = [{'map': 'a', 'pending': ['item']}]
    assert not check_run(data, collect_observed=True)[0]['passed']
