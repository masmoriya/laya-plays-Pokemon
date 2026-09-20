from types import SimpleNamespace

from jpp.agent.policy_adapter import ProviderPolicy
from jpp.character.animation import Animation
from jpp.game_adapter import GenericGBCAdapter, adapter_for_rom
from jpp.progress.badge_tracker import BadgeTracker
from jpp.recovery.recovery_manager import RecoveryManager
from jpp.recovery.stuck_detector import StuckDetector
from jpp.rules import GameRules
from jpp.telemetry import Event, EventType, RunStore
from jpp import symbols as S


def test_badge_tracker_reports_new_badge():
    memory = bytearray(0x10000)
    memory[S.OBTAINED_BADGES] = 1
    tracker = BadgeTracker()
    update = tracker.update(memory)
    assert update.badge_ids == ("boulder",)
    assert update.new_badge_event == "boulder"
    assert tracker.update(memory).new_badge_event is None


def test_stuck_detector_scores_repeated_location():
    detector = StuckDetector(window=8, warning=0.7, recovery=0.85)
    state = SimpleNamespace(map_id=1, x=2, y=3, in_battle=False)
    for _ in range(8):
        detector.observe(state, "reach")
    assert detector.needs_warning
    assert detector.needs_recovery


def test_recovery_rejects_untrusted_action():
    provider = SimpleNamespace(recover=lambda state, history: {"action": "shell"})
    decision = RecoveryManager(provider).decide({}, [])
    assert decision.action == "wait"


def test_provider_policy_enforces_option_allowlist():
    provider = SimpleNamespace(decide_tactical=lambda state, options: {"action": "bad"})
    decision = ProviderPolicy(provider).decide(SimpleNamespace(kind="tie", state={}, options={"safe": "ok"}))
    assert decision.option == "safe"
    assert decision.fell_back


def test_run_store_keeps_run_id_and_events(tmp_path):
    store = RunStore(tmp_path / "jev.sqlite", "red-001")
    store.emit(Event(EventType.RUN_STARTED, "red-001", {"mode": "test"}))
    store.remember("failure", "loop", 0.8)
    assert store.stats()["run_id"] == "red-001"
    assert store.relevant_memories()[0]["text"] == "loop"
    store.close()


def test_animation_has_looping_frame():
    animation = Animation()
    assert animation.frame(now=animation.started_at + 2.0) in range(4)


def test_gbc_rom_uses_generic_adapter_until_gen2_ram_map_exists():
    adapter = adapter_for_rom("Gold 97 Reforged v6.1c.gbc")
    assert isinstance(adapter, GenericGBCAdapter)
    assert not adapter.supports_ram_progress
    assert adapter.snapshot(None).title == "GOLD REFORGED"


def test_rules_choose_preferred_legal_starter_and_keep_jev_name():
    rules = GameRules()
    assert rules.player_name == "JEV"
    assert rules.choose_starter({"choose_totodile": "legal", "choose_chikorita": "legal"}) == "choose_chikorita"
    assert rules.choose_starter({"choose_eevee": "legal"}) == "choose_eevee"
    assert rules.choose_starter({"slot_1": "Totodile"}) == "slot_1"
