import json
from types import SimpleNamespace

from jpp.agent.game_loop import play
from jpp.agent.policy_adapter import ProviderPolicy


class Emulator:
    def __init__(self):
        self.pressed = []
        self.ticks = 0

    def button(self, name, frames):
        self.pressed.append((name, frames))

    def tick(self, frames=1):
        self.ticks += frames


class Adapter:
    title = "GOLD 97 REFORGED"

    def snapshot(self, emulator):
        state = SimpleNamespace(
            map_name="MAP_01_02",
            x=3,
            y=4,
            in_battle=False,
            party=(),
            badge_ids=("johto_1",),
            badge_total=16,
            pokedex_caught_ids=(155,),
            pokedex_seen_ids=(152, 155),
            pokedex_species=("UNKNOWN", "BULBASAUR", "CHIKORITA"),
        )
        return SimpleNamespace(state=state, title=self.title)


def test_generic_agent_loop_uses_allowlisted_controls_and_logs_state(tmp_path):
    log = tmp_path / "gold.jsonl"
    emulator = Emulator()
    records = play(
        emulator, Adapter(), ProviderPolicy(_Provider()), 1, log_path=log
    )
    assert records[0]["kind"] == "generic"
    assert records[0]["state"]["pokedex"] == {"caught": 1, "seen": 2, "total": 2}
    assert emulator.pressed == [("up", 8)]
    assert json.loads(log.read_text())["choice"] == "up"


class _Provider:
    model = "test"

    def decide_tactical(self, state, options):
        assert state["game"] == "GOLD 97 REFORGED"
        assert "up" in options
        return {"action": "up"}
