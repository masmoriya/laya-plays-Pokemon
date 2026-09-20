"""Evidence-first progress through the supplied Gold 97 route."""

from dataclasses import dataclass, field
from pathlib import Path


_ROUTE = Path(__file__).resolve().parents[2] / "config/gold97_route.tsv"


def _route():
    main, optional = {}, []
    if not _ROUTE.exists():
        return main, optional
    for line in _ROUTE.read_text().splitlines():
        parts = line.split("\t")
        if parts[0] == "main" and len(parts) == 3:
            main[int(parts[1])] = parts[2]
        elif parts[0] == "optional" and len(parts) == 4:
            optional.append((parts[1], int(parts[2]), parts[3]))
    return main, optional


MAIN, OPTIONAL = _route()
_BADGE_STEPS = {5: 1, 10: 2, 15: 3, 21: 4, 32: 5, 39: 6, 44: 7}
# Gold 97's Brass Tower interior spans group 3, while the actual top is a
# separate roof map. Reaching an interior floor is not proof of completing step 4.
BRASS_TOWER_ROOF = (14, 10)
_MAP_COMPLETIONS = {4: BRASS_TOWER_ROOF}
_ARRIVALS = {
    1: "Silent Town", 3: "Pagota City",
    9: "Westport City", 17: "Birdon Town", 23: "Sunpoint City",
    31: "Alloy City", 38: "Blue Forest", 43: "Stand City",
    61: "Kanto", 87: "Westport Docks", 94: "Amami Town",
    97: "Ryukyu City", 99: "Kume City",
}


@dataclass
class RouteProgress:
    completed: set[int] = field(default_factory=set)
    optional_completed: set[str] = field(default_factory=set)
    manual_history: list[int] = field(default_factory=list)

    @property
    def now(self):
        return next((step for step in MAIN if step not in self.completed), None)

    def observe(self, state):
        badges = len(getattr(state, "badge_ids", ()))
        for step, count in _BADGE_STEPS.items():
            if badges >= count:
                self.completed.add(step)
        map_key = (getattr(state, "map_group", None), getattr(state, "map_number", None))
        for step, target in _MAP_COMPLETIONS.items():
            if map_key == target:
                self.completed.add(step)
        area = getattr(state, "area_name", "")
        for step, target in _ARRIVALS.items():
            if target == area or (target == "Kanto" and "Kanto" in area):
                self.completed.add(step)

    def confirm(self):
        step = self.now
        if step is not None:
            self.completed.add(step)
            self.manual_history.append(step)
        return step

    def correct(self):
        while self.manual_history:
            step = self.manual_history.pop()
            if step in self.completed:
                self.completed.remove(step)
                return step
        return None

    def toggle_optional(self, identifier):
        if identifier not in {item[0] for item in OPTIONAL}:
            return False
        if identifier in self.optional_completed:
            self.optional_completed.remove(identifier)
        else:
            self.optional_completed.add(identifier)
        return True

    def display(self):
        current = self.now
        next_steps = [step for step in MAIN if current is not None and step > current and step not in self.completed]
        later = next_steps[1] if len(next_steps) > 1 else None
        optional = next((item for item in OPTIONAL if item[0] not in self.optional_completed
                         and current is not None and item[1] <= current), None)
        return {
            "now": (current, MAIN[current]) if current is not None else None,
            "next": (next_steps[0], MAIN[next_steps[0]]) if next_steps else None,
            "later": (later, MAIN[later]) if later is not None else None,
            "optional": optional,
            "done": len(self.completed), "total": len(MAIN),
        }

    def to_dict(self):
        return {"completed": sorted(self.completed),
                "optional_completed": sorted(self.optional_completed),
                "manual_history": list(self.manual_history)}

    @classmethod
    def from_dict(cls, payload):
        payload = payload or {}
        return cls({int(i) for i in payload.get("completed", ()) if int(i) in MAIN},
                   set(payload.get("optional_completed", ())),
                   [int(i) for i in payload.get("manual_history", ()) if int(i) in MAIN])
