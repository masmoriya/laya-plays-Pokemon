"""Validated observations shared by navigation and its display."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MapSnapshot:
    terrain: object
    position: tuple[int, int]
    entities: tuple
    destination: object
    exits: tuple = ()
    frame_number: int = 0
    connections: tuple = ()


class LiveMapState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.snapshot = None
        self.status = "Map unavailable"

    def update(self, state, terrain, *, ready, overworld, entities=(), destination=None, connections=()):
        if not getattr(state, "map_width", 0) or not getattr(state, "map_height", 0):
            self.reset()
            return
        key = (state.map_group, state.map_number)
        previous = self.snapshot
        if previous and (previous.terrain.map_key != key or
                         previous.terrain.width != state.map_width or
                         previous.terrain.height != state.map_height):
            self.reset()
        if getattr(state, "in_battle", False) or not ready:
            self.snapshot = None
            self.status = "Updating map"
            return
        if not overworld:
            # Menus retain the last coherent same-map snapshot, including overlays.
            return
        x, y = state.x, state.y
        if (terrain is None or terrain.map_key != key or
                terrain.width != state.map_width or terrain.height != state.map_height or
                len(terrain.tiles) != terrain.width * terrain.height or
                x is None or y is None or not 0 <= x < terrain.width or
                not 0 <= y < terrain.height):
            self.reset()
            return
        self.snapshot = MapSnapshot(terrain, (x, y), tuple(entities), destination,
                                    tuple(getattr(state, "map_exits", ())),
                                    getattr(state, "frame_number", 0), tuple(dict(c) for c in connections))
        self.status = ""
