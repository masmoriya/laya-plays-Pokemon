"""Gold97 controller composition shared by live and headless runners."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from .gold97_memory import Gold97Memory
from .gold97_dialogue import DialogueProgress
from .gold97_playback import Playback
from .gold97_training import Training
from .gold97_party import PartyReorder
from .gold97_roster_service import RosterService
from .gold97_rewards import RewardLedger
from .gold97_policy_config import reward_weights
from ..live_map_state import LiveMapState
from .journey_strategy import JourneyStrategy
from .gold97_navigation import MovementHistory
from .gold97_opening import Gold97Opening
from .gold97_battle import Gold97BattleStrategy
from .gold97_battle_executor import BattleExecutor
from .gold97_vision import LunaScreenReader
from ..route_progress import RouteProgress
from .policy_adapter import ProviderPolicy
from .providers.jev_provider import JevProvider
from .usage import UsageTotals

from .controller_provider import ProviderLifecycle
from .controller_navigation import NavigationExecution
from .controller_services import ServiceExecution
from .controller_encounter import EncounterExecution
from .controller_tick import TickExecution
from .controller_decision import DecisionExecution

class Gold97Controller(ProviderLifecycle, NavigationExecution, ServiceExecution, EncounterExecution, TickExecution, DecisionExecution):
    def __init__(self, run_id, *, database="data/jev.sqlite", policy=None,
                 vision=None, vision_enabled=True, save_encounter=None,
                 restore_encounter=None, restore_stuck=None, strategy_provider=None):
        self.memory = Gold97Memory(run_id, database)
        self.dialogue = DialogueProgress()
        self.playback = Playback(self.memory)
        self.rewards = RewardLedger(self.memory, reward_weights())
        self.map_state = LiveMapState()
        self.training = Training(self.memory)
        self.party_reorder = PartyReorder()
        self.roster_service = RosterService(self)
        self.opening = Gold97Opening()
        self.route = RouteProgress.from_dict(self.memory.world.get("route"))
        self.opening_goal = None
        self.navigation_target = None
        self.policy = policy or ProviderPolicy(JevProvider())
        self.vision = vision if vision is not None else (LunaScreenReader() if vision_enabled else None)
        self.save_encounter = save_encounter
        self.restore_encounter = restore_encounter
        self.restore_stuck = restore_stuck
        self.stuck_restores = 0
        # A slow screen read or health check must not queue walking decisions.
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.vision_future = None
        self.decision_future = None
        self.decision_key = None
        self.vision_key = None
        self.screen_note = None
        self.last = None
        self.cooldown = 0
        self.stalls = 0
        self.movement_history = MovementHistory()
        self.replans_at = {}
        self.unknown_frames = 0
        self.no_options_frames = 0
        self.paused = False
        self.pause_reason = ""
        self.encounter = None
        self.pending_frames = 0
        self.attempts = {}
        self.title_bootstrap_done = False
        self.last_decision = None
        self.latest_model_input = None
        self.last_battle = None
        self.healing = None
        self.recovery = None
        self.shopping = None
        self.shopping_skip = set()
        self.capture = None
        self.wait_streak = 0
        self.terrain = None
        self.usage = UsageTotals()
        self.held_action = None
        self.last_move_direction = None
        self.interaction_positions = set()
        self.interaction_map_key = None
        self.attempted_items = set()
        self.battle_strategy = Gold97BattleStrategy()
        self.battle_executor = BattleExecutor()
        self.wild_battle_committed = False
        self.battle_phase = None
        self.battle_target = None
        self.battle_cursor_index = 0
        self.battle_pp_before = None
        self.battle_foe_hp_before = None
        self.battle_switch_target = None
        self.battle_switch_phase = None
        self.battle_switch_text = None
        self.learning_move = None
        self.provider_health_future = None
        self.provider_health = "unknown"
        self.provider_health_error = ""
        self.provider_health_checked_at = monotonic()
        self.provider_events = deque(maxlen=500)
        self.strategy = JourneyStrategy(self, strategy_provider, enabled=vision_enabled)
        self.action_source = "idle"
        self._start_provider_health_check()


    def observe(self, state, entities=(), overworld=True, terrain=None, prompt_visible=None):
        """Also called during manual play and provider outages; never presses keys."""
        self.memory.experience.observe(state)
        self.map_state.update(state, terrain, ready=terrain is not None,
                              overworld=overworld, entities=entities,
                              destination=self.navigation_target, connections=self.strategy.data['connections'])
        snapshot = self.map_state.snapshot
        self.terrain = snapshot.terrain if snapshot and overworld else terrain
        previous_goal = self.route.now
        self.route.observe(state)
        if self.memory.world.get('route') != self.route.to_dict():
            self.memory.world['route'] = self.route.to_dict()
            self.memory.save()
        self.strategy.observe(state, entities, overworld, prompt_visible)
        self.rewards.observe(state, self.route)
        self.rewards.observe_exploration(state, overworld=overworld)
        self.training.observe(state, self.route)
        if self.route.now != previous_goal:
            self.export_notes('milestone')


    def manual_pause(self):
        self.memory.experience.interrupt('Manual pause; action outcome not yet verified')
        if self.party_reorder.phase:
            self.party_reorder.phase = 'close'
        if self.roster_service.transfer.phase:
            self.roster_service.transfer.phase = 'close'
        self.roster_service.target = None
        self.playback.request(False)
        self.strategy.invalidate()
        self.held_action = None
        self.paused = False
        self.pause_reason = ''
        self.export_notes('pause')


    def step(self, state, *, frame=None, entities=(), overworld=True,
             terrain=None, prompt_visible=None):
        self.last_decision = None
        if overworld or state.in_battle:
            self.dialogue.reset()
        self.observe(state, entities, overworld, terrain, prompt_visible)
        action = self._step(state, frame=frame, entities=entities, overworld=overworld,
                            terrain=terrain, prompt_visible=prompt_visible)
        if self.playback.requested and not self.paused and self.provider_health == 'ready':
            self.playback.ready()
        if self.paused:
            action = None
            self.held_action = None
        self.action_source = (
            self._provider_label() if action and self.last_decision and self.last_decision.request_made else
            "deterministic execution" if action else
            "paused" if self.paused else
            "awaiting Luna" if self.strategy.future else
            f"awaiting {self._provider_label()}" if self.decision_future else "idle")
        if action:
            payload = self.last_decision.model_input if self.last_decision else None
            self.memory.experience.action(state, action, self.action_source, self.route.now, payload)
        return action


    def close(self):
        self.memory.experience.interrupt('Session ended before a verified outcome')
        self.export_notes('exit')
        if self.strategy.future:
            self.strategy.future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        provider = getattr(self.policy, "provider", None)
        close_provider = getattr(provider, "close", None)
        if callable(close_provider):
            close_provider()
        self.memory.close()


    def usage_snapshot(self):
        return self.usage.snapshot()
