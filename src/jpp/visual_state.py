"""Small, explicitly attributed state view for supported cartridge adapters."""


def adapter_facts(adapter, emulator):
    state = adapter.snapshot(emulator).state
    return {"source": "supported-game-adapter", "title": adapter.title,
            "map": state.map_name, "position": {"x": state.x, "y": state.y},
            "badges": state.badges, "battle": state.battle.kind,
            "party": [{"species": mon.species, "level": mon.level,
                       "hp": mon.hp, "max_hp": mon.max_hp} for mon in state.party]}
