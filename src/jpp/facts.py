"""Every number Jev would get wrong, computed here and handed over as a word.

CONTEXT section 4's second jaggedness risk: "is 14/33 HP low against a level 5 Squirtle"
is a division and two hops. So fractions, type multipliers and PP counts are resolved
before the call and the model only ever reads a label.
"""

from . import gamedata

EFFECTIVENESS_WORDS = (
    (0.0, "no effect against"),
    (0.5, "not very effective against"),
    (1.0, "neutral against"),
    (2.0, "super effective against"),
)

HP_WORDS = (
    (0.0, "fainted"),
    (0.2, "critical"),
    (0.5, "hurt"),
    (0.85, "scratched"),
    (1.0, "healthy"),
)


def type_multiplier(attack_type: str, defender_types) -> float:
    multiplier = 1.0
    for defender in defender_types:
        multiplier *= gamedata.TYPE_CHART.get((attack_type, defender), 1.0)
    return multiplier


def effectiveness_word(multiplier: float) -> str:
    if multiplier == 0:
        return EFFECTIVENESS_WORDS[0][1]
    if multiplier < 1:
        return EFFECTIVENESS_WORDS[1][1]
    if multiplier == 1:
        return EFFECTIVENESS_WORDS[2][1]
    return EFFECTIVENESS_WORDS[3][1]


def hp_word(fraction: float) -> str:
    for threshold, word in HP_WORDS:
        if fraction <= threshold:
            return word
    return "healthy"


def move_id(name: str) -> int | None:
    for i, entry in gamedata.MOVES.items():
        if entry[0] == name:
            return i
    return None


def describe_move(name: str, pp_left: int, defender_types) -> str:
    """The option sentence, with the derived facts already inside it."""
    i = move_id(name)
    _, move_type, power, max_pp = gamedata.move(i) if i else (name, "NORMAL", 0, 0)
    word = effectiveness_word(type_multiplier(move_type, defender_types))
    target = "/".join(defender_types)
    kind = "attack with" if power else "use"
    return (
        f"{kind} {name}, a {move_type.title()} move, "
        f"{pp_left} of {max_pp} PP left, {word} {target}"
    )


def describe_switch(mon) -> str:
    return (
        f"switch to {mon.species}, level {mon.level}, "
        f"{hp_word(mon.hp_fraction)} at {mon.hp}/{mon.max_hp} HP; "
        "the opponent gets a free turn"
    )


def battle_summary(mon) -> dict:
    """The trimmed fields that go into state. No inventory, no badges, no event flags."""
    return {
        "species": mon.species,
        "level": mon.level,
        "hp_fraction": mon.hp_fraction,
        "condition": hp_word(mon.hp_fraction),
        "status": mon.status,
        "types": list(mon.types),
    }
