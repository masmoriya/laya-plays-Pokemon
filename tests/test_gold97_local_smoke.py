"""Opt-in cartridge proof: GOLD97_ROM and GOLD97_STATE must be user-owned files."""

import os
from pathlib import Path

import pytest

from jpp.agent.gold97_play import play_gold97
from jpp.gold97_adapter import Gold97Adapter
from jpp.policy import Decision


@pytest.mark.skipif(not os.environ.get("GOLD97_ROM") or not os.environ.get("GOLD97_STATE"),
                    reason="provide a local Gold 97 ROM and save state")
def test_bounded_cartridge_play_without_model_calls(tmp_path):
    from pyboy import PyBoy

    rom = Path(os.environ["GOLD97_ROM"])
    state = Path(os.environ["GOLD97_STATE"])
    adapter = Gold97Adapter(rom)
    emulator = PyBoy(str(rom), window="null")

    class Policy:
        def decide(self, branch):
            action = "up" if "up" in branch.options else next(iter(branch.options))
            return Decision(option=action, probabilities={action: 1.0})

    class Vision:
        def describe(self, frame):
            return {"mode": "menu", "screen_text": ["CONTINUE"], "uncertainty": ""}

    try:
        with state.open("rb") as handle:
            emulator.load_state(handle)
        for _ in range(5):
            emulator.tick()
        records = play_gold97(
            emulator, adapter, Policy(), 2, run_id="smoke",
            database=tmp_path / "agent.sqlite", checkpoint_dir=tmp_path / "checkpoints",
            vision=Vision(),
        )
        assert len(records) == 2
        assert all(record["choice"] in {"a", "b", "up", "down", "left", "right"}
                   for record in records)
    finally:
        emulator.stop(save=False)
