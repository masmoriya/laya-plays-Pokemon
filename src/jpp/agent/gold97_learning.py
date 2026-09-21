"""Guard irreversible Gold 97 level-up move choices with whole-set value."""

import re

from ..gold97_catalog import move_names
from .gold97_battle import _GOLD97_TYPE_CHART, _move_data, _move_name, _type_multiplier


_IMPORTANT_UTILITY = {
    "RECOVER": 30, "MILK DRINK": 30, "MORNING SUN": 27,
    "MOONLIGHT": 27, "SYNTHESIS": 27, "SLEEP POWDER": 29,
    "SPORE": 34, "HYPNOSIS": 22, "THUNDER WAVE": 24,
    "STUN SPORE": 20, "TOXIC": 23, "SWORDS DANCE": 26,
    "AMNESIA": 23, "CONFUSE RAY": 19, "LEECH SEED": 26,
    "REFLECT": 18, "LIGHT SCREEN": 18, "PROTECT": 18,
    "BELLY DRUM": 22, "AGILITY": 17, "REST": 20,
}
_FIELD_MOVES = frozenset({"CUT", "FLY", "SURF", "STRENGTH", "FLASH",
                          "WATERFALL", "WHIRLPOOL"})
_VARIABLE_POWER = {"RETURN": 80, "FRUSTRATION": 70, "HIDDEN POWER": 60,
                   "MAGNITUDE": 70, "FLAIL": 50, "REVERSAL": 50,
                   "NIGHT SHADE": 40, "SEISMIC TOSS": 40,
                   "DRAGON RAGE": 40, "SONICBOOM": 20}


def _contains_move(text, name):
    name = _move_name(name)
    return re.search(r"(?<![A-Z0-9])" + re.escape(name) + r"(?![A-Z0-9])",
                     _move_name(text)) is not None


def proposed_move(state):
    """Read a named move only from visible learn dialogue, never guess from order."""
    lines = tuple(getattr(state, "screen_lines", ()) or ())
    text = _move_name(" ".join(lines[-6:]))
    learn = re.search(r"\bLEARN(?:ING)?\b", text)
    if learn is None:
        return None
    after = text[learn.end():].strip()
    # A later list of current moves can remain visible under "can't learn
    # more than four moves". Only a move directly following LEARN is evidence
    # of the offered move; otherwise the menu must fail closed.
    matches = [name for name in move_names()
               if re.match(re.escape(_move_name(name)) + r"(?![A-Z0-9])", after)]
    return max(matches, key=len) if matches else None


def _attack_value(name, types):
    _, move_type, power, pp = _move_data(name)
    power = _VARIABLE_POWER.get(_move_name(name), power)
    if power is None or power <= 0:
        return None
    # Gen II STAB and the actual Dark/Steel type chart matter beyond this fight.
    strength = min(power, 120) * (1.5 if move_type in types else 1.0)
    if pp and pp < 10:
        strength *= 0.83
    return move_type, strength


def _set_value(moves, types):
    attacks = [attack for name in moves
               if (attack := _attack_value(name, types)) is not None]
    if not attacks:
        offense = 0.0
    else:
        # Best available answer to each defensive type, with diminishing value
        # for a second attack of the same type. This preserves Ember as unique
        # Fire STAB while allowing Bite to replace redundant weak Normal damage.
        offense = sum(max((power * _type_multiplier(kind, (target,))
                           for kind, power in attacks), default=0)
                      for target in _GOLD97_TYPE_CHART) / len(_GOLD97_TYPE_CHART)
        offense += 0.08 * sum(sorted((power for _, power in attacks), reverse=True)[:2])
    utility = {}
    for name in moves:
        normalized = _move_name(name)
        if _attack_value(name, types) is not None:
            continue
        power = _move_data(name)[2]
        important = _IMPORTANT_UTILITY.get(normalized)
        role = normalized if important is not None or power is None else "minor_status"
        value = (important if important is not None else
                 35 if power is None else 0 if normalized == "SPLASH" else 5)
        utility[role] = max(value, utility.get(role, 0))
    return offense + sum(utility.values())


def replacement_index(mon, new_move):
    """Return the slot worth replacing, or None if the new set is not better."""
    moves = tuple(getattr(mon, "moves", ()) or ())
    if len(moves) != 4 or any(_move_name(move) == _move_name(new_move)
                              for move in moves):
        return None
    types = {_move_name(kind) for kind in getattr(mon, "types", ()) or ()}
    baseline = _set_value(moves, types)
    candidates = [(index, _set_value(moves[:index] + (new_move,) + moves[index + 1:], types))
                  for index, move in enumerate(moves)
                  if _move_name(move) not in _FIELD_MOVES]
    if not candidates:
        return None
    index, value = max(candidates, key=lambda candidate: (candidate[1], candidate[0]))
    return index if value > baseline + 0.01 else None


def learning_menu_step(state, new_move):
    """Return (action, detail) for a confirmed four-move forgetting screen.

    None means this is not the move menu. A recognized but unreadable menu
    returns (None, detail) so the controller can pause rather than press A.
    """
    lines = tuple(getattr(state, "screen_lines", ()) or ())
    if getattr(state, "battle_menu_kind", None) in {"command", "moves"}:
        return None
    cancel = next((row for row, line in enumerate(lines)
                   if "CANCEL" in line.upper()), None)
    cursor = getattr(state, "screen_cursor", None)
    partial = False
    for mon in getattr(state, "party", ()):
        moves = tuple(getattr(mon, "moves", ()) or ())
        if len(moves) != 4:
            continue
        rows = [next((row for row, line in enumerate(lines)
                      if _contains_move(line, name)), None) for name in moves]
        partial |= cancel is not None and sum(row is not None for row in rows) >= 2
        if any(row is None for row in rows) or len(set(rows)) != 4:
            continue
        if not new_move or cursor is None or cursor[1] not in range(len(lines)):
            return None, "Move-learning menu is missing its move or cursor"
        target = replacement_index(mon, new_move)
        if target is None:
            if cancel is None:
                return None, "Cannot locate cancel on the move-learning menu"
            detail = f"Keep {mon.species}'s current moves instead of learning {new_move}"
        else:
            detail = f"Learn {new_move} in place of {moves[target]}"
        target_row = cancel if target is None else rows[target]
        action = ("down" if cursor[1] < target_row else
                  "up" if cursor[1] > target_row else "a")
        return action, detail
    uncertain_moves = (new_move and cursor is not None and
                       sum(any(_contains_move(line, name) for line in lines)
                           for name in move_names()) >= 2)
    if partial or uncertain_moves or (cursor is not None and
                                      any("FORGET" in line.upper() or
                                          "DELETE" in line.upper() for line in lines)):
        return None, "Move-learning menu is not fully readable"
    return None
