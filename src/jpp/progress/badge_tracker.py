"""Eight-bit Gen 1 badge tracker."""

from dataclasses import dataclass

from .. import symbols as S

BADGES = ("boulder", "cascade", "thunder", "rainbow", "soul", "marsh", "volcano", "earth")


@dataclass(frozen=True)
class BadgeUpdate:
    badge_count: int
    badge_ids: tuple[str, ...]
    new_badge_event: str | None = None


class BadgeTracker:
    def __init__(self):
        self._last = 0

    def update(self, memory) -> BadgeUpdate:
        mask = int(memory[S.OBTAINED_BADGES])
        earned = tuple(name for bit, name in enumerate(BADGES) if mask & (1 << bit))
        new = mask & ~self._last
        event = BADGES[(new & -new).bit_length() - 1] if new else None
        self._last = mask
        return BadgeUpdate(len(earned), earned, event)

