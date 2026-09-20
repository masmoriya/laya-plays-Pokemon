"""Typed event names and append-only event records."""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import time


class EventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    LOCATION_CHANGED = "LOCATION_CHANGED"
    OBJECTIVE_STARTED = "OBJECTIVE_STARTED"
    OBJECTIVE_COMPLETED = "OBJECTIVE_COMPLETED"
    MODEL_THINKING = "MODEL_THINKING"
    MODEL_DECISION = "MODEL_DECISION"
    BATTLE_STARTED = "BATTLE_STARTED"
    BATTLE_ENDED = "BATTLE_ENDED"
    POKEMON_CAUGHT = "POKEMON_CAUGHT"
    POKEMON_FAINTED = "POKEMON_FAINTED"
    POKEMON_EVOLVED = "POKEMON_EVOLVED"
    BADGE_EARNED = "BADGE_EARNED"
    STUCK_DETECTED = "STUCK_DETECTED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_SUCCEEDED = "RECOVERY_SUCCEEDED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    STATE_SAVED = "STATE_SAVED"
    PROCESS_RESTARTED = "PROCESS_RESTARTED"
    STREAM_CONNECTED = "STREAM_CONNECTED"
    STREAM_DISCONNECTED = "STREAM_DISCONNECTED"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"


@dataclass(frozen=True)
class Event:
    type: EventType | str
    run_id: str
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self):
        value = asdict(self)
        value["type"] = str(self.type)
        return value

