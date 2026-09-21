"""Gold97 controller services responsibilities."""

from .gold97_items import item_cell
from .gold97_opening import _route
from .gold97_services import center_retreat_target, center_target, is_center, is_mart, mart_target, needs_healing, nurse_target, should_buy_balls
from .gold97_shopping import mart_menu_step
from .controller_constants import _MOVE_HOLD_FRAMES

class ServiceExecution:
    def _service_route(self, state, target, goal, *, arrival=None):
        """Walk to a service entrance using the same collision-aware route as story goals."""
        if state.x is None or state.y is None or target is None:
            return None
        position = (state.x, state.y)
        self.navigation_target = ((state.map_group, state.map_number), target)
        self.opening_goal = goal
        if position == target:
            # A warp at the map edge can require another step in its entrance
            # direction. A at the doorway leaves the player there forever.
            return arrival
        key = f"{state.map_group:02X}:{state.map_number:02X}"
        action = _route(self.memory.map(key), position, target,
                        state.map_width, state.map_height,
                        avoid=self.interaction_positions | {
                            item_cell(e) for e in (self.map_state.snapshot.entities
                                                  if self.map_state.snapshot else ())},
                        terrain=self.terrain)
        if action:
            self.opening_goal = goal
            self.last = (key, position, action)
            self.held_action = action
            self.cooldown = _MOVE_HOLD_FRAMES
        return action


    def _recovery_action(self, state, *, overworld, prompt_visible=False):
        """Return a deterministic heal route, or None when no safe route is known."""
        if state.in_battle or not getattr(state, "party", ()):
            return None
        town_key = (state.map_group, state.map_number)
        check_in = (center_target(state) is not None and
                    getattr(state, "last_spawn_map", town_key) != town_key)
        if self.recovery is None and (needs_healing(state) or check_in):
            self.recovery = {"started": True, "attempts": 0}
            self._set_provider_event("Visiting the local Pokémon Center")
        if self.recovery is None:
            return None
        if is_center(state):
            from .gold97_services import fully_recovered
            if fully_recovered(state):
                self.recovery["exit"] = True
            if self.recovery.get("exit"):
                if not overworld:
                    return "a" if prompt_visible else None
                return self._service_route(state, (5, 7),
                                           "Leave the Pokémon Center", arrival="down")
            target = nurse_target(state)
            if not overworld:
                return "a" if prompt_visible else None
            if (state.x, state.y) == target:
                self._set_provider_event("Healing the party at the Pokémon Center")
                if not self.recovery.get("faced_nurse"):
                    self.recovery["faced_nurse"] = True
                    # Arrival coordinates can update before the walking animation
                    # finishes. Hold the facing direction before tapping A across
                    # the counter; a one-frame turn can be ignored by the ROM.
                    self.cooldown = _MOVE_HOLD_FRAMES
                    return "up"
                self.recovery["attempts"] += 1
                if self.recovery["attempts"] > 8:
                    self.pause("Pokémon Center nurse did not restore HP")
                    return None
                return "a"
            return self._service_route(state, target, "Heal at the Pokémon Center")
        if self.recovery.get("exit"):
            self.recovery = None
            self._set_provider_event("Pokémon Center visit complete")
            return None
        if not overworld:
            # A menu may already be open when the heal threshold is crossed.
            # Close it before sending walking directions toward the Center.
            return "b" if prompt_visible else None
        entrance = center_target(state)
        if entrance is None:
            retreat = center_retreat_target(state)
            if retreat is None:
                return None
            target, arrival = retreat
            return self._service_route(state, target,
                                       "Retreat to the Pokémon Center",
                                       arrival=arrival)
        action = self._service_route(state, entrance[0],
                                     "Return to the Pokémon Center", arrival="up")
        if action:
            self._set_provider_event("Returning to the Pokémon Center")
        return action


    def _shopping_action(self, state, *, overworld):
        """Buy Poké Balls only when the visible Mart screen confirms each step."""
        if self.recovery is not None or state.in_battle:
            return None
        if self.shopping is None:
            if not should_buy_balls(state):
                return None
            target = mart_target(state)
            if target is None:
                return None
            shop_key = ((state.map_group, state.map_number), state.money,
                        state.poke_ball_count)
            if shop_key in self.shopping_skip:
                return None
            self.shopping = {"target": target[0], "town": shop_key,
                             "last_balls": state.poke_ball_count,
                             "selected_ball": False, "last_ui": None,
                             "repeats": 0, "talks": 0}
            self._set_provider_event("Heading to the Mart for Poké Balls")
        plan = self.shopping
        if not is_mart(state):
            if plan.get("exit"):
                self.shopping = None
                return None
            return self._service_route(state, plan["target"], "Buy Poké Balls",
                                       arrival="up")
        if plan.get("exit"):
            if not overworld:
                return "b"
            return self._service_route(state, (4, 7), "Leave the Mart",
                                       arrival="down")
        balls = getattr(state, "poke_ball_count", 0)
        if balls > plan["last_balls"]:
            plan["last_balls"] = balls
            plan["selected_ball"] = False
            plan["last_ui"] = None
            plan["repeats"] = 0
            self._set_provider_event(f"Bought Poké Balls; now carrying {balls}")
        if not should_buy_balls(state):
            plan["exit"] = True
            return "b" if not overworld else self._service_route(
                state, (4, 7), "Leave the Mart", arrival="down")
        if not overworld:
            step = mart_menu_step(plan, state)
            if step is None:
                if (getattr(state, "screen_cursor", None) is None and
                        plan.get("transitions", 0) < 3):
                    # The indoor warp and Mart text can take several frames to
                    # finish drawing. Wait for a readable menu, without ever
                    # confirming an unidentified item or quantity prompt.
                    plan["transitions"] = plan.get("transitions", 0) + 1
                    return "wait"
                plan["exit"] = True
                self.shopping_skip.add((plan["town"][0], state.money, balls))
                self._set_provider_event("Mart screen unclear; leaving without using an item")
                return "b"
            action, phase = step
            plan["transitions"] = 0
            ui = (phase, getattr(state, "screen_cursor", None),
                  tuple(getattr(state, "screen_lines", ()) or ()))
            plan["repeats"] = plan["repeats"] + 1 if ui == plan["last_ui"] else 0
            plan["last_ui"] = ui
            if plan["repeats"] >= 3:
                plan["exit"] = True
                self.shopping_skip.add((plan["town"][0], state.money, balls))
                self._set_provider_event("Mart menu did not advance; leaving")
                return "b"
            return action
        if state.x is None or state.y is None:
            return None
        # The counter tile (2, 3) is blocked. Talk across it from (3, 3).
        clerk_tile = (3, 3)
        if (state.x, state.y) == clerk_tile:
            if not plan.get("faced_clerk"):
                plan["faced_clerk"] = True
                self.cooldown = _MOVE_HOLD_FRAMES
                return "left"
            plan["talks"] += 1
            if plan["talks"] > 3:
                plan["exit"] = True
                self.shopping_skip.add((plan["town"][0], state.money, balls))
                return self._service_route(state, (4, 7), "Leave the Mart",
                                           arrival="down")
            return "a"
        return self._service_route(state, clerk_tile, "Buy Poké Balls")
