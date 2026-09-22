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
    objects: tuple = ()
    trail: tuple = ()


class LiveMapState:
    def __init__(self):
        from .agent.discovery import DisplayMemory
        self.discovery = DisplayMemory()
        self.reset()

    def reset(self):
        self.snapshot = None
        self.status = "Map unavailable"

    def update(self, state, terrain, *, ready, overworld, entities=(), destination=None, connections=(), objects=(), trail=()):
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
        from .agent.discovery import ObservedTerrain, observe_terrain
        if not isinstance(terrain, ObservedTerrain):
            terrain = observe_terrain(self.discovery, state, terrain, overworld)
        entities = tuple(e for e in entities if (e.pixel_x//16, e.pixel_y//16) in terrain.visible_objects)
        if destination and (destination[0] != key or tuple(destination[1]) not in terrain.seen):
            destination = None
        self.snapshot = MapSnapshot(terrain, (x, y), tuple(entities), destination,
                                    tuple(getattr(terrain, "exits", getattr(state, "map_exits", ()))),
                                    getattr(state, "frame_number", 0), tuple(dict(c) for c in connections),
                                    tuple(dict(o) for o in objects), tuple(tuple(p) for p in trail))
        self.status = ""
