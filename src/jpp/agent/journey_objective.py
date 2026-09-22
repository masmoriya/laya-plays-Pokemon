"""Identify unfinished leader interactions from observed introductions."""

import re

from ..gold97_catalog import map_details


def objective_speaker(npc, goal):
    """A conversation is not evidence that a defeat objective is complete.

    Require a self-introduction, not a guide merely mentioning the leader.
    The cartridge text decoder can omit the apostrophe/m in "I'm".
    """
    match = re.fullmatch(r"Defeat (.+?) in (.+? Gym)", goal, re.IGNORECASE)
    if not match or "observed_from" in npc:
        return None
    try:
        group, number = (int(part, 16) for part in npc["map"].split(":"))
    except (KeyError, ValueError):
        return None
    name, gym = match.groups()
    if map_details(group, number)[0].casefold() != gym.casefold():
        return None
    introduction = rf"\bI\s*(?:AM\s+|['’]?M\s+)?{re.escape(name)}\b"
    if any(re.search(introduction, page, re.IGNORECASE) for page in npc.get("pages", ())):
        return name
    return None
