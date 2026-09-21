"""Bounded text-only Jev state from confirmed cartridge readings."""


def _mon(mon):
    if mon is None:
        return None
    return {"species": mon.species, "level": mon.level, "hp": mon.hp,
            "max_hp": mon.max_hp, "types": list(mon.types),
            "moves": list(mon.moves), "pp": list(mon.pp), "status": mon.status}


def decision_state(state, memory, note, key, position):
    return {
        "decision_kind": "gold97_battle" if state.in_battle else "explore",
        "goal": "Discover the cartridge's story through play; catch only verified new wild species",
        "map": state.area_name, "position": position,
        "party": [_mon(mon) for mon in state.party],
        "money": getattr(state, "money", None),
        "poke_balls": getattr(state, "poke_ball_count", None),
        "badges": list(state.badge_ids),
        "caught": [state.pokedex_species[index] for index in state.pokedex_caught_ids],
        "memory": memory.relevant(key), "screen": note,
        "screen_text": list(getattr(state, "screen_lines", ())),
        "visited_here": memory.map(key)["visited"][-16:],
        "battle": ({"kind": state.battle.kind, "active": _mon(state.battle.active),
                    "opponent": _mon(state.battle.opponent)} if state.in_battle else None),
    }
