"""Count only completed battles with a result observed on the exit edge."""


class BattleProgress:
    def __init__(self, battles=0, wins=0, losses=0):
        self.battles, self.wins, self.losses = battles, wins, losses
        self._active = False
        self.opponent = None
        self.last_result = None
        self.last_opponent = None

    def update(self, state):
        active = bool(getattr(state, "in_battle", False))
        if active:
            opponent = getattr(getattr(state, "battle", None), "opponent", None)
            self.opponent = getattr(opponent, "species", None)
        result = None
        if self._active and not active:
            code = getattr(state, "battle_result", None)
            if code is not None:
                code &= ~0xC0  # Caught/box-full flags accompany the outcome.
            if code in (0, 1, 2):
                result = ("win", "loss", "draw")[code]
                self.last_result = result
                self.last_opponent = self.opponent or "unknown"
                self.battles += 1
                self.wins += int(code == 0)
                self.losses += int(code == 1)
            else:
                # The exit edge proves an encounter ended even when this cartridge
                # does not expose a trustworthy result byte.
                result = "result unavailable"
                self.last_result = result
                self.last_opponent = self.opponent or "unknown"
                self.battles += 1
            self.opponent = None
        self._active = active
        return result
