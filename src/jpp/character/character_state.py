"""Jev identity and event-driven visual state."""

from enum import StrEnum


class CharacterState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    DECIDED = "decided"
    BATTLE = "battle"
    CELEBRATE = "celebrate"
    CONFUSED = "confused"
    RECOVERING = "recovering"
    HURT = "hurt"
    SLEEP = "sleep"


EVENT_STATES = {
    "MODEL_THINKING": CharacterState.THINKING,
    "MODEL_DECISION": CharacterState.DECIDED,
    "BATTLE_STARTED": CharacterState.BATTLE,
    "BADGE_EARNED": CharacterState.CELEBRATE,
    "POKEMON_CAUGHT": CharacterState.CELEBRATE,
    "POKEMON_EVOLVED": CharacterState.CELEBRATE,
    "STUCK_DETECTED": CharacterState.CONFUSED,
    "RECOVERY_STARTED": CharacterState.RECOVERING,
    "POKEMON_FAINTED": CharacterState.HURT,
    "STREAM_DISCONNECTED": CharacterState.SLEEP,
}

