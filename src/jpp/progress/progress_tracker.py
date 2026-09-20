"""Viewer-facing progress snapshot. Counts remain durable through RunStore."""

from dataclasses import asdict, dataclass, field
import time


@dataclass
class Progress:
    run_id: str = "run-001"
    player_name: str = "JEV"
    badges: tuple[str, ...] = ()
    badge_total: int = 8
    current_map: str = "UNKNOWN"
    map_history: list[str] = field(default_factory=list)
    current_objective: str = "Start the journey"
    completed_objectives: list[str] = field(default_factory=list)
    party: list[dict] = field(default_factory=list)
    key_items: list[str] = field(default_factory=list)
    pokedex_caught: int = 0
    pokedex_seen: int = 0
    pokedex_total: int = 0
    pokedex_caught_species: list[str] = field(default_factory=list)
    battles: int = 0
    wins: int = 0
    losses: int = 0
    fainted: int = 0
    caught: int = 0
    evolutions: int = 0
    decisions: int = 0
    recovery_events: int = 0
    stuck_events: int = 0
    saves: int = 0
    crashes: int = 0
    restarts: int = 0
    active_play_seconds: float = 0.0
    started_at: float = field(default_factory=time.time)
    stream_started_at: float = field(default_factory=time.time)
    game_time: str = "--:--"

    @property
    def run_seconds(self):
        return max(0.0, self.active_play_seconds + time.time() - self.started_at)

    @property
    def stream_seconds(self):
        return max(0.0, time.time() - self.stream_started_at)

    def seal_active_time(self):
        self.active_play_seconds = self.run_seconds
        self.started_at = time.time()

    @property
    def badge_count(self):
        return len(self.badges)

    def update_from_state(self, state):
        self.current_map = state.map_name
        map_name = str(state.map_name or "")
        map_known = map_name not in {"", "UNKNOWN", "MAP_UNAVAILABLE", "MAP_00_00"}
        if map_known and (not self.map_history or self.map_history[-1] != state.map_name):
            self.map_history = [*self.map_history, state.map_name][-6:]
        self.party = [
            {
                "species": mon.species,
                "level": mon.level,
                "hp": mon.hp,
                "max_hp": mon.max_hp,
                "status": mon.status,
                "held_item": getattr(mon, "held_item", None),
            }
            for mon in state.party
            if getattr(mon, "level", 0) > 0
            and not str(getattr(mon, "species", "")).startswith("MON_")
        ]
        self.key_items = list(getattr(state, "key_items", self.key_items) or ())
        self.badges = tuple(getattr(state, "badge_ids", self.badges))
        self.badge_total = int(getattr(state, "badge_total", self.badge_total))
        caught_ids = getattr(state, "pokedex_caught_ids", None)
        seen_ids = getattr(state, "pokedex_seen_ids", None)
        if caught_ids is not None and seen_ids is not None:
            species = getattr(state, "pokedex_species", ())
            self.pokedex_caught = len(caught_ids)
            self.pokedex_seen = len(seen_ids)
            # Gold 97 exposes a sentinel at index 0; other adapters may expose a
            # zero-based species list. Do not bake Red/Gold indexing into the HUD.
            offset = 1 if species and species[0] == "UNKNOWN" else 0
            self.pokedex_total = max(0, len(species) - offset)
            self.pokedex_caught_species = [species[i] for i in caught_ids if i < len(species)]

    def to_dict(self):
        value = asdict(self)
        value["run_seconds"] = round(self.run_seconds, 1)
        value["stream_seconds"] = round(self.stream_seconds, 1)
        value["badge_count"] = self.badge_count
        return value


class ProgressTracker:
    def __init__(self, run_id="run-001", started_at=None, player_name="JEV", map_history=None,
                 active_play_seconds=0.0):
        clean_history = [
            item for item in (map_history or ())
            if str(item) not in {"", "UNKNOWN", "MAP_UNAVAILABLE", "MAP_00_00"}
        ]
        self.progress = Progress(
            run_id=run_id,
            player_name=player_name,
            started_at=started_at or time.time(),
            map_history=clean_history[-6:],
            active_play_seconds=float(active_play_seconds or 0),
        )

    def update(self, state, badge_update=None):
        self.progress.update_from_state(state)
        if badge_update:
            self.progress.badges = badge_update.badge_ids
        return self.progress
