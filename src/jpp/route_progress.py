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
_MAP_COMPLETIONS = {4: BRASS_TOWER_ROOF, 24: (0x13, 0x0D)}
_ARRIVALS = {
    1: "Silent Town", 3: "Pagota City",
    9: "Westport City", 11: "Teknos City", 17: "Birdon Town", 22: "Sunpoint City",
    18: "Slowpoke Well B1F",
    31: "Alloy City", 38: "Blue Forest", 43: "Stand City",
    61: "Kanto", 87: "Westport Docks", 94: "Amami Town",
    97: "Ryukyu City", 99: "Kume City",
}


@dataclass
class RouteProgress:
    completed: set[int] = field(default_factory=set)
    optional_completed: set[str] = field(default_factory=set)
    manual_history: list[int] = field(default_factory=list)
    field_moves: list[dict] = field(default_factory=list, init=False, repr=False)

    @property
    def now(self):
        return next((step for step in MAIN if step not in self.completed), None)

    def observe(self, state):
        # The scripted opening rival encounter is complete before the player
        # reaches Route 101 with a starter. This also repairs older journeys
        # whose tracker did not observe the battle itself.
        if (getattr(state, "area_name", "") in {"Route 101", "Silent Hills", "Pagota City"}
                and getattr(state, "party", ())):
            self.completed.update((1, 2))
        if getattr(state, "mechanics_verified", False):
            self.completed.update(step for step in getattr(state, "story_milestones", ())
                                  if step in {1, 2, 3, 4, 9, 11, 12, 13, 14, 16, 18})
        badges = len(getattr(state, "badge_ids", ()))
        if getattr(state, "received_cut_from_bill", False):
            self.completed.add(6)
        if getattr(state, "route_102_tree_chopped", False):
            self.completed.add(7)
        if getattr(state, "route_102_rival_complete", False):
            self.completed.add(8)
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
        # Sunpoint City and its Docks are separate objectives. Older route
        # tracking marked both complete on city arrival, leaving no active
        # destination to guide exploration toward the ship.
        if area == "Sunpoint City":
            if 23 not in self.manual_history:
                self.completed.discard(23)
            self.completed.add(22)
        if ((getattr(state, 'map_group', None), getattr(state, 'map_number', None)) == (0x13, 0x0A)
                or area == "Sunpoint Docks"):
            self.completed.add(23)

        from .field_moves import capabilities
        self.field_moves = capabilities(state, self.now)

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
            "field_moves": self.field_moves,
        }

    def to_dict(self):
        return {"completed": sorted(self.completed),
                "optional_completed": sorted(self.optional_completed),
                "manual_history": list(self.manual_history)}

    @classmethod
    def from_dict(cls, payload):
        payload = payload or {}
        completed = {int(i) for i in payload.get("completed", ()) if int(i) in MAIN}
        manual = [int(i) for i in payload.get("manual_history", ()) if int(i) in MAIN]
        # The cartridge initializes this warning flag before the rescue. Older
        # readers mistook it for the later return-to-Teknos story event.
        if 12 not in completed and 13 not in manual:
            completed.discard(13)
        return cls(completed, set(payload.get("optional_completed", ())), manual)
