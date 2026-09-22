"""Explicit success gates; reaching a benchmark budget is not a passing run."""


def check_run(result, *, milestones=(), pickups=0, collect_observed=False, max_loops=None):
    checks = []
    for milestone in milestones:
        checks.append({'check': 'new_verified_milestone', 'expected': milestone,
                       'passed': milestone in result['new_verified_milestones']})
    navigation = result['navigation']
    if pickups:
        actual = len(navigation['new_pickups'])
        checks.append({'check': 'minimum_new_pickups', 'expected': pickups,
                       'actual': actual, 'passed': actual >= pickups})
    if collect_observed:
        remaining = navigation['pending_collectibles']
        departures = navigation['departures_with_pending_collectibles']
        checks.append({'check': 'observed_collectibles_resolved', 'pending': remaining,
                       'departures': departures, 'passed': not remaining and not departures})
    if max_loops is not None:
        actual = result['event_counts'].get('loop_recovery', 0)
        checks.append({'check': 'maximum_loop_recoveries', 'expected': max_loops,
                       'actual': actual, 'passed': actual <= max_loops})
    return checks
