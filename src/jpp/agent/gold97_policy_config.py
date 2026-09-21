"""Optional per-install reward weights; survival and training limits remain fixed."""
import json
import os
from pathlib import Path

from .gold97_rewards import DEFAULT_WEIGHTS


def reward_weights():
    path = Path(os.environ.get('JPP_GOLD97_POLICY', 'config/gold97_policy.json'))
    if not path.exists():
        return dict(DEFAULT_WEIGHTS)
    configured = json.loads(path.read_text()).get('reward_weights', {})
    if not isinstance(configured, dict) or set(configured) - set(DEFAULT_WEIGHTS):
        raise ValueError('Unknown Gold 97 reward weights')
    if any(type(value) is not int or value < 0 for value in configured.values()):
        raise ValueError('Gold 97 reward weights must be nonnegative integers')
    return {**DEFAULT_WEIGHTS, **configured}
