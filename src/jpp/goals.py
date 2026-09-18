"""The goal stack. Code owns it; Jev never sees more than the goal's sentence.

Ordered, not parallel: Oak blocks Route 1 until the starter is in hand. Every predicate
reads RAM, and the one that depends on a battle outcome reads the latch, never
`wBattleResult` directly.
"""

from dataclasses import dataclass
from typing import Callable

from . import symbols as S


@dataclass(frozen=True)
class Goal:
    name: str
    sentence: str  # the `goal` field sent to Jev, next to the thing being judged
    complete: Callable[[object, object], bool]


GOALS = (
    Goal(
        "leave_house",
        "Get out of the house and into Pallet Town.",
        # "out of the house", not "in Pallet Town": the stack has no memory, so a
        # predicate that names one map un-completes itself the moment the next goal
        # walks off that map.
        lambda st, latch: st.map_id not in (S.REDS_HOUSE_1F, S.REDS_HOUSE_2F),
    ),
    Goal(
        "get_starter",
        "Get a starter Pokemon from Professor Oak in his lab.",
        lambda st, latch: len(st.party) >= 1 and st.event(S.EVENT_GOT_STARTER),
    ),
    Goal(
        "win_lab_rival",
        "Win the rival battle in Oak's lab without the party fainting.",
        lambda st, latch: (
            st.event(S.EVENT_BATTLED_RIVAL_IN_OAKS_LAB) and latch.result == latch.WIN
        ),
    ),
    Goal(
        "reach_viridian",
        "Walk north out of Pallet Town, up Route 1, into Viridian City.",
        lambda st, latch: st.map_id == S.VIRIDIAN_CITY,
    ),
)


class GoalStack:
    """Advances, never regresses. A completed goal stays completed."""

    def __init__(self, goals=GOALS):
        self.goals = goals
        self.index = 0

    @property
    def current(self) -> Goal | None:
        return self.goals[self.index] if self.index < len(self.goals) else None

    @property
    def done(self) -> bool:
        return self.index >= len(self.goals)

    def advance(self, state, latch) -> Goal | None:
        while self.current and self.current.complete(state, latch):
            self.index += 1
        return self.current
