"""Gold97 controller navigation responsibilities."""

from .gold97_items import item_action, is_item_entity, item_cell
from .controller_constants import _KNOWN_EXITS, _MENU_COOLDOWN_FRAMES, _MOVE_HOLD_FRAMES, _REVERSE, _STEPS

class NavigationExecution:
    @staticmethod
    def _location(state):
        return (f"{state.map_group:02X}:{state.map_number:02X}",
                (state.x, state.y))


    def _observe_move(self, state):
        if state.x is None or state.y is None or not state.map_group:
            return
        key, position = self._location(state)
        self.memory.visited(key, position)
        self.movement_history.observe(key, position)
        if self.last:
            old_key, origin, action = self.last
            if action in _STEPS and old_key == key:
                if position != origin:
                    delta = (position[0] - origin[0], position[1] - origin[1])
                    observed = next((d for d, step in _STEPS.items() if step == delta), None)
                    self.last_move_direction = observed
                    self.memory.move_result(key, origin, action, position)
                    self._set_provider_event(
                        f"Moved {observed or 'across tiles'} to {position[0]},{position[1]}"
                    )
                    self.live.result(f"Position {position[0]},{position[1]}")
                    self.stalls = 0
                    self.replans_at.pop((key, origin), None)
                    self.last = None
                    from .route_execution import committed_heading
                    keep_walking = committed_heading(self, state, action)
                    self.held_action = action if keep_walking else None
                    if keep_walking:
                        self.memory.world['continued_route_steps'] = self.memory.world.get('continued_route_steps', 0) + 1
                        self.last = (key, position, action)
                    self.cooldown = _MOVE_HOLD_FRAMES if keep_walking else 0
                elif self.cooldown == 0 and not getattr(state, "player_moving", False):
                    self.held_action = None
                    self.memory.move_result(key, origin, action, position)
                    self._set_provider_event(
                        f"Blocked {action} at {position[0]},{position[1]}"
                    )
                    self.live.result(f"Blocked at {position[0]},{position[1]}")
                    self.stalls += 1
                    self.last = None
                    if self.stalls >= 8:
                        place = (key, position)
                        cycles = self.replans_at.get(place, 0) + 1
                        self.replans_at[place] = cycles
                        self.stalls = 0
                        self.decision_future = None
                        self.screen_note = None
                        self.cooldown = 12
                        self._set_provider_event(
                            f"Replanning from map at {position[0]},{position[1]}"
                        )
                        return True
            elif old_key != key:
                self.held_action = None
                self.memory.remember("exit", f"{old_key} {origin} -> {key} {position}")
                self.last = None


    def _options(self, state, entities, overworld=True):
        if state.in_battle:
            foe = state.battle.opponent
            if foe is None:
                return {}
            return {"a": "confirm highlighted battle command", "b": "back or cancel",
                    "up": "move battle cursor up", "down": "move battle cursor down",
                    "left": "move battle cursor left", "right": "move battle cursor right"}
        if not overworld:
            from .journey_prerequisites import ferry_menu_options
            ferry = ferry_menu_options(state, self.route.now)
            if ferry:
                return ferry
            text = ' '.join(getattr(state, 'screen_lines', ())).upper()
            if any(word in text for word in ('BUY', 'SELL', 'HOW MANY', 'WILL BE', 'DOLL')):
                return {'b': 'leave shopping without an approved supply purchase'}
            if any(word in text for word in ('RELEASE', 'DEPOSIT', 'WITHDRAW', 'CHANGE BOX', 'STATS')):
                return {'b': 'leave an unowned roster menu'}
            from .gold97_choices import dialogue_options
            choices = dialogue_options(self, state)
            if choices is not None:
                return choices
            if getattr(state, 'screen_cursor', None) is not None:
                return {'b': 'cancel an unidentified menu'}
            return {"a": "advance current dialogue"}
        if state.x is None or state.y is None or not state.map_group:
            return {}
        key, position = self._location(state)
        blocked = self.memory.map(key)["blocked"]
        options = {}
        walkable = {}
        for direction, (dx, dy) in _STEPS.items():
            target = (position[0] + dx, position[1] + dy)
            if (0 <= target[0] < state.map_width and
                    0 <= target[1] < state.map_height and
                    (self.terrain is None or self.terrain.allows(target, direction))):
                walkable[direction] = f"walk {direction} toward {target}"
                if [list(position), direction] not in blocked:
                    options[direction] = walkable[direction]
        visited = {tuple(point) for point in self.memory.map(key)["visited"]}
        unexplored = {
            direction: description for direction, description in options.items()
            if (position[0] + _STEPS[direction][0],
                position[1] + _STEPS[direction][1]) not in visited
        }
        if unexplored:
            options = unexplored
        exit_target = _KNOWN_EXITS.get((state.map_group, state.map_number))
        if exit_target and options:
            improving = {
                direction: description for direction, description in options.items()
                if abs(position[0] + _STEPS[direction][0] - exit_target[0])
                + abs(position[1] + _STEPS[direction][1] - exit_target[1])
                < abs(position[0] - exit_target[0]) + abs(position[1] - exit_target[1])
            }
            if improving:
                options = improving
        if self.last_move_direction and len(options) > 1:
            options.pop(_REVERSE[self.last_move_direction], None)
        if self.interaction_positions:
            options = {
                direction: description for direction, description in options.items()
                if (position[0] + _STEPS[direction][0],
                    position[1] + _STEPS[direction][1]) not in self.interaction_positions
            }
        if not options:
            # Blocked-edge memory can be stale after a transition or an input
            # timing miss. Retry a terrain-permitted step before inventing an
            # interaction with a nearby NPC or an empty doorway.
            options = {
                direction: description for direction, description in walkable.items()
                if (position[0] + _STEPS[direction][0],
                    position[1] + _STEPS[direction][1]) not in self.interaction_positions
            } or walkable
        return options


    def _item_detour(self, state, entities, *, overworld):
        """Give a visible item a first-class goal before story navigation."""
        if state.in_battle or not overworld:
            return None
        item_entities = tuple(entity for entity in entities if is_item_entity(entity))
        if not item_entities:
            return None
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        position = (state.x, state.y)
        item_positions = {item_cell(entity) for entity in item_entities}
        item_positions.discard(None)
        if position in self.interaction_positions:
            item_positions = {point for point in item_positions if point != position}
        action = item_action(self.memory, state, item_entities,
                             terrain=self.terrain, avoid=self.interaction_positions,
                             attempted=self.attempted_items)
        if action is None:
            return None
        target = min((point for point in item_positions if (key, point) not in self.attempted_items),
                     key=lambda point: abs(point[0] - position[0]) +
                     abs(point[1] - position[1]), default=None)
        if target is None:
            return None
        self.opening_goal = "Collect the nearby item before continuing"
        if action == "a":
            self.attempted_items.add((key, target))
            self.interaction_positions.add(position)
            self._set_provider_event("Collecting nearby item before continuing")
        else:
            self._set_provider_event("Heading to a nearby item before continuing")
        self.last = (key, position, action)
        self.held_action = action if action in _STEPS else None
        self.cooldown = (_MOVE_HOLD_FRAMES if action in _STEPS
                         else _MENU_COOLDOWN_FRAMES)
        return action
