"""Display identifiers for the Reforged build, transcribed from its constants.

The tabular names/dimensions in config are factual identifiers, not graphics.
Unknown versions deliberately fall back to an unavailable label.
"""

from functools import lru_cache
from pathlib import Path


_CONFIG = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=None)
def _table(name):
    path = _CONFIG / f"gold97_{name}.tsv"
    if not path.exists():
        return ()
    return tuple(line.split("\t") for line in path.read_text().splitlines() if line)


def _display(name):
    words = name.replace("POKECENTER", "POKÉMON_CENTER").replace("OAKS", "OAK'S").split("_")
    return " ".join(word if word in {"1F", "2F", "B1F", "B2F", "B3F", "B4F", "B5F"} else word.title() for word in words)


@lru_cache(maxsize=None)
def _maps():
    return {(int(group), int(number)): (name, int(width), int(height))
            for group, number, name, width, height in _table("maps")}


def map_details(group, number):
    value = _maps().get((group, number))
    if not value:
        return ("Area unavailable", "", 0, 0)
    name, width, height = value
    area = _display(name)
    locality = next((_display(prefix) for prefix in (
        "SILENT_TOWN", "PAGOTA_CITY", "WESTPORT_CITY", "TEKNOS_CITY",
        "BIRDON_TOWN", "SANSKRIT_TOWN", "SUNPOINT_CITY", "ALLOY_CITY",
        "BLUE_FOREST", "FROSTPOINT_TOWN", "STAND_CITY", "AMAMI_TOWN",
        "RYUKYU_CITY", "KUME_CITY") if name.startswith(prefix.split("_")[0])), "")
    if name.startswith("OAKS_LAB"):
        locality = "Silent Town"
    if name == "SILENT_TOWN":
        locality = ""
    return area, locality, width, height


@lru_cache(maxsize=None)
def _names(kind):
    return {int(index): _display(name) for index, name in _table(kind)}


def item_name(item_id):
    readable = {"Psncureberry": "Poison-cure Berry", "Przcureberry": "Paralysis-cure Berry",
                "Brnhealberry": "Burn-heal Berry", "Iceberry": "Ice Berry"}
    if item_id == 0:
        return None
    label = _names("items").get(item_id, f"Item {item_id:02X}")
    return readable.get(label, label)


def move_name(move_id):
    return _names("moves").get(move_id, f"Move {move_id:02X}")
