"""Gold97 controller encounter responsibilities."""

from .gold97_services import novel_capture
from .controller_constants import _MAX_CAPTURE_ATTEMPTS

class EncounterExecution:
    def _finish_encounter(self, state):
        if not self.encounter or state.in_battle or not self.encounter["started"]:
            return
        encounter = self.encounter
        self.encounter = None
        if encounter["species_id"] in state.pokedex_caught_ids:
            self.memory.remember("capture", encounter["species"], encounter["map"])
            return
        key = (encounter["map"], encounter["species_id"])
        self.attempts[key] = self.attempts.get(key, 0) + 1
        self.pause("Static encounter ended without a capture; inspect before continuing")


    @staticmethod
    def _escape_action(state):
        visible_menu = getattr(state, "battle_menu_kind", None)
        if visible_menu == "moves":
            return "b"
        if visible_menu == "text":
            lines = tuple(getattr(state, "screen_lines", ()) or ())
            if any("CANCEL" in line or "USE" in line for line in lines):
                return "b"
            return "a"
        cursor = getattr(state, "battle_menu_cursor", None)
        if cursor is None or cursor == (2, 2):
            return "a"
        if cursor[0] != 2:
            return "right"
        return "down"


    def _capture_action(self, state):
        """Use the battle PACK on a new hack-exclusive species, never on old ones."""
        foe = state.battle.opponent
        if not novel_capture(state, foe):
            self.capture = None
            return None
        # A weak party gets out of a wild encounter first.  Capturing is a
        # useful detour only when the active team can safely continue.
        from .gold97_readiness import affordable_fight
        active = getattr(state.battle, 'active', None) or next(iter(state.party), None)
        if (self.training.readiness(state).conserve or active is None
                or not affordable_fight(active, foe, extra_turns=2)):
            self.capture = None
            return None
        balls = getattr(state, "poke_ball_count", None)
        if balls is None or balls <= 0:
            self._set_provider_event("No Poké Balls; escaping the encounter")
            self.capture = {"species_id": foe.species_id, "phase": "escape",
                            "attempts": 0, "balls": 0, "steps": 0}
            return self._escape_action(state)
        if self.capture is None or self.capture.get("species_id") != foe.species_id:
            self.capture = {"species_id": foe.species_id, "phase": "menu",
                            "attempts": 0, "balls": balls, "steps": 0}
        plan = self.capture
        if balls < plan["balls"]:
            plan["attempts"] += plan["balls"] - balls
            plan["balls"] = balls
            plan["steps"] = 0
        if plan["attempts"] >= _MAX_CAPTURE_ATTEMPTS or plan["steps"] >= 12:
            plan["phase"] = "escape"
        if plan["phase"] == "escape":
            self._set_provider_event("Capture attempt ended; leaving the encounter")
            return self._escape_action(state)
        plan["steps"] += 1
        visible_menu = getattr(state, "battle_menu_kind", None)
        cursor = getattr(state, "battle_menu_cursor", None)
        if visible_menu == "moves":
            return "b"
        if visible_menu == "command" or visible_menu is None:
            # The ROM orders FIGHT/PKMN on the first row and PACK/RUN below.
            if cursor == (1, 2):
                plan["phase"] = "bag"
                return "a"
            if cursor is None:
                return "a"
            if cursor[0] == 2:
                return "left"
            return "down" if cursor[1] == 1 else "a"
        lines = tuple(getattr(state, "screen_lines", ()) or ())
        ball_row = next((row for row, line in enumerate(lines)
                         if "POK" in line.upper() and "BALL" in line.upper()), None)
        if ball_row is not None and any("USE" in line for line in lines):
            self._set_provider_event(f"Using a Poké Ball on {foe.species}")
            plan["phase"] = "throw"
            return "a"
        if ball_row is not None:
            screen_cursor = getattr(state, "screen_cursor", None)
            if screen_cursor and screen_cursor[1] != ball_row:
                return "down" if screen_cursor[1] < ball_row else "up"
            plan["phase"] = "select_ball"
            return "a"
        if any("CANCEL" in line for line in lines):
            # The bag initially opens in ITEMS, with POTION highlighted. Switch
            # pockets; never confirm an unidentified item as a Poké Ball.
            return "right"
        return "a"


    def _battle_reset(self):
        self.wild_battle_committed = False
        self.battle_strategy.reset()
        self.battle_executor.reset()
        self.battle_phase = None
        self.battle_target = None
        self.battle_cursor_index = 0
        self.battle_pp_before = None
        self.battle_foe_hp_before = None
        self.battle_switch_target = None
        self.battle_switch_phase = None
        self.battle_switch_text = None


    def _trainer_battle_action(self, state):
        return self.battle_executor.step(self, state)
