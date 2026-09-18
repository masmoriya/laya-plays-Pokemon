"""Legal actions, described by intent, plus one state builder per branch kind.

Two rules do the work here. Jev picks from a deck the code already proved legal, so it
cannot name a button or an option that does not exist. And each branch kind builds its own
state: sending the whole world is CONTEXT section 4's first jaggedness risk, and a padded
state measurably moves the answer.
"""

from dataclasses import dataclass

from . import facts, symbols as S


@dataclass(frozen=True)
class Branch:
    """What the classifier hands to Jev: a kind, a state body, the legal options."""

    kind: str
    state: dict
    options: dict

POTION = 0x14  # constants/item_constants.asm
ITEM_NAMES = {POTION: "Potion"}
POTION_HEAL = 20


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def bag(mem) -> dict[int, int]:
    """item id -> quantity, from wNumBagItems / wBagItems."""
    count = min(mem[S.NUM_BAG_ITEMS], 20)
    return {
        mem[S.BAG_ITEMS + i * 2]: mem[S.BAG_ITEMS + i * 2 + 1] for i in range(count)
    }


def battle_options(state, items: dict[int, int] | None = None) -> dict[str, str]:
    """Moves with PP left, healthy bench members, and a Potion if one is in the bag."""
    active, foe = state.battle.active, state.battle.opponent
    out: dict[str, str] = {}
    for name, pp in zip(active.moves, active.pp):
        if pp > 0:
            out[f"use_move_{_slug(name)}"] = facts.describe_move(name, pp, foe.types)
    for mon in state.party:
        if mon.fainted or mon.species == active.species:
            continue
        out[f"switch_to_{_slug(mon.species)}"] = facts.describe_switch(mon)
    missing = active.max_hp - active.hp
    if items and items.get(POTION) and missing:
        out["use_item_potion"] = (
            f"use a Potion, restores {POTION_HEAL} HP of {missing} missing"
        )
    if state.battle.kind == "wild":
        out["run_away"] = "run away from this wild Pokemon and keep walking the route"
    return out


def battle_branch(state, goal, items=None, turn=None) -> Branch:
    active, foe = state.battle.active, state.battle.opponent
    body = {
        "goal": goal.sentence,
        "battle": {
            "kind": state.battle.kind,
            "active": facts.battle_summary(active),
            "opponent": facts.battle_summary(foe),
        },
        "party": [
            facts.battle_summary(m) | {"slot": m.slot}
            for m in state.party
            if not m.fainted and m.species != active.species
        ],
    }
    if turn is not None:
        body["battle"]["turn"] = turn
    opts = battle_options(state, items)
    body["options"] = opts
    return Branch("battle", body, opts)


def tie_branch(state, goal, waypoint, free: list[str]) -> Branch:
    """The overworld tie: blocked, and two sidesteps are equally good."""
    opts = {
        f"step_{d}": f"take one step {d} and try again from there" for d in sorted(free)
    }
    body = {
        "goal": goal.sentence,
        "current_map": state.map_name,
        "position": {"x": state.x, "y": state.y},
        "waypoint": {"x": waypoint[0], "y": waypoint[1]},
        "options": opts,
    }
    return Branch("tie", body, opts)


def dialogue_branch(state, goal, visible_text: str, choices: list[str]) -> Branch:
    opts = {f"answer_{_slug(c)}": f"answer {c}" for c in choices}
    body = {
        "goal": goal.sentence,
        "visible_text": visible_text,
        "options": opts,
    }
    return Branch("dialogue", body, opts)


# --- turning a chosen option back into button presses ---
# The Gen 1 battle menu is FIGHT / PKMN on the top row, ITEM / RUN below.
# ponytail: this cursor choreography is written from the menu layout, not measured. Run
# `jpp probe` on a ROM and watch wCurrentMenuItem while pressing, then fix any sequence
# that does not land. A wrong sequence costs a wasted turn, never a corrupted save.
MENU_ROOT = {"fight": [], "pkmn": ["right"], "item": ["down"], "run": ["right", "down"]}


def buttons_for(state, branch: Branch, option: str) -> list[str]:
    if branch.kind in ("tie", "dialogue"):
        if option.startswith("step_"):
            return [option[len("step_") :]]
        return ["a"]
    active = state.battle.active
    if option.startswith("use_move_"):
        names = [n for n, pp in zip(active.moves, active.pp) if pp > 0]
        index = names.index(
            next(n for n in names if _slug(n) == option[len("use_move_") :])
        )
        return MENU_ROOT["fight"] + ["a"] + ["down"] * index + ["a"]
    if option.startswith("switch_to_"):
        bench = [m for m in state.party if not m.fainted]
        index = next(
            i
            for i, m in enumerate(bench)
            if _slug(m.species) == option[len("switch_to_") :]
        )
        return MENU_ROOT["pkmn"] + ["a"] + ["down"] * index + ["a", "a"]
    if option == "use_item_potion":
        return MENU_ROOT["item"] + ["a", "a", "a"]
    if option == "run_away":
        return MENU_ROOT["run"] + ["a"]
    return ["a"]
