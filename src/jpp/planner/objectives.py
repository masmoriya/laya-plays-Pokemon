"""Small hierarchical campaign seed. Expand one badge at a time."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Objective:
    key: str
    label: str
    parent: str | None = None


OBJECTIVES = (
    Objective("campaign", "Become Pokemon Champion"),
    Objective("boulder_badge", "Earn the Boulder Badge", "campaign"),
    Objective("pewter_city", "Reach Pewter City", "boulder_badge"),
    Objective("pewter_gym", "Defeat Brock", "boulder_badge"),
)

