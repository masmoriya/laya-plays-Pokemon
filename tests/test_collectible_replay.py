"""Opt-in real checkpoint run: collectible coverage through the shared controller."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from jpp.benchmark import run


def test_real_pickups_and_resource_harvest_at_accelerated_speed(tmp_path):
    checkpoint = os.environ.get('GOLD97_COLLECTIBLE_STATE')
    database = os.environ.get('GOLD97_MEMORY_DATABASE')
    if not checkpoint or not database:
        pytest.skip('requires a real checkpoint with two pickups and a harvestable resource')
    checkpoint = Path(checkpoint)
    before = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    output = tmp_path / 'report'
    args = SimpleNamespace(
        rom=os.environ.get('GOLD97_ROM', 'Gold 97 Reforged v6.1c.gbc'),
        state=str(checkpoint), database=database,
        run_id=os.environ.get('GOLD97_RUN_ID', 'laya-tested'),
        provider='executor', modes=['off'], repeats=1, frames=6000,
        seconds=60, speed=100, output=str(output),
        require_pickups=3, require_observed_collection=True, max_loop_recoveries=0,
    )
    assert run(args) == 0
    report = json.loads((output / 'comparison.json').read_text())
    result = report['runs'][0]
    assert result['verdict'] == 'passed'
    nav = result['navigation']
    assert report['checkpoint_sha256'] == before
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == before
    assert len(nav['new_pickups']) >= 3
    assert len(nav['new_harvests']) >= 1
    assert not nav['pending_collectibles']
    assert not nav['departures_with_pending_collectibles']
    assert nav['repeated_steps'] == 0
    assert result['stop_reason'] == 'model_choice_required'
    assert result['achieved_speed'] > 0  # Report measured speed, never assume 100x.
    assert not any(totals['calls'] for totals in result['usage'].values())
